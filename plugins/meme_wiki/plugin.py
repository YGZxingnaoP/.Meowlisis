# -*- coding: utf-8 -*-
"""Meowlisis 梗库插件（独立实现，不 import 主项目代码）。

它只做三件事：
1. 记住梗：Meowlisis梗 <词> 描述：... 接法：...
2. 查梗：Meowlisis查梗            → 把整库 JSON 转成 Markdown 发到当前群/私聊
3. 召回：普通消息进来时，找到相关梗，把【描述 + 接法】交给角色模型，
   由角色自己组织回复；插件不发送任何预设台词。

注意：本项目的插件 API 没有「回复前注入上下文」的钩子，所以第 3 步由插件
调用角色模型（ctx.prompt + ctx.llm）完成；回复内容仍由角色生成。
"""

import json
import os
import re
import shutil
import threading
import time
import unicodedata

_EDGE = " \t\r\n，,。.！!？?:：；;、~～…\"'“”‘’「」『』（）()[]【】{}<>《》"

_ASK = re.compile(
    r"(?:是)?(?:什么梗|啥梗|什么来头|什么来历|什么出处|什么意思|是什么意思|"
    r"啥意思|是啥意思|是啥|怎么用|怎么接|怎么玩|如何用|怎么来的|哪儿来的|"
    r"哪来的|咋来的|谁说的)(?:啊|呀|呢|的|啊这是)?[？?。！!~～]*$"
)
_PRONOUN = {"这", "那", "它", "他", "她", "你", "我", "这个", "那个", "这句话", "那句话"}
_STOP = {
    "在吗", "在不在", "哈哈", "哈哈哈", "笑死", "好的", "好吧", "晚安", "早安",
    "睡觉", "吃饭", "干嘛", "没事", "收到", "谢谢", "好耶", "草", "典", "乐",
}


def _norm(text) -> str:
    s = unicodedata.normalize("NFKC", str(text or "")).strip().strip(_EDGE)
    return s.lower()


def _bigrams(text):
    s = _norm(text)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _coverage(query, text) -> float:
    q, t = _bigrams(query), _bigrams(text)
    if not q or not t:
        return 0.0
    return len(q & t) / len(q)


class Plugin:
    id = "meme_wiki"
    title = "Meowlisis 梗库"
    version = "1.0.0"
    default_enabled = True

    # 插件框架要求的默认方法
    def trigger_tools(self):
        return []

    def interface_tools(self):
        return []

    def prompt_hint(self):
        return ""

    def state_decl(self):
        return {}

    # ==================== 生命周期 ====================
    def setup(self, ctx):
        self.ctx = ctx
        self.log = ctx.log
        self.config = dict(ctx.config or {})
        self._base = ctx.data_dir(per_user="")
        self._path = os.path.join(self._base, "user_terms.json")
        self._lock = threading.Lock()
        self._entries = self._load()
        self._last_reply = {}
        self.log.info(f"[meme_wiki] 梗库已加载 {len(self._entries)} 条：{self._path}")

    def teardown(self):
        self.ctx = None

    # ==================== 配置 ====================
    def _int(self, key, default):
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _float(self, key, default):
        try:
            return float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _bool(self, key, default=False):
        return bool(self.config.get(key, default))

    def _admin(self, uid):
        admin = self.config.get("admin_qqs", []) or []
        if isinstance(admin, str):
            admin = [x.strip() for x in re.split(r"[,，\s]+", admin) if x.strip()]
        return str(uid) in {str(x) for x in admin}

    def _can_add(self, uid):
        mode = str(self.config.get("allow_add", "all") or "all").strip().lower()
        if mode in ("off", "0", "false", "关", "禁止"):
            return False
        if mode in ("admin", "管理员"):
            return self._admin(uid)
        return True

    # ==================== 存储 ====================
    def _load(self):
        data = []
        try:
            if not os.path.isfile(self._path):
                return data
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                raw = list(raw.values())
            if not isinstance(raw, list):
                return data
            for item in raw:
                if isinstance(item, str):
                    entry = {"text": item}
                elif isinstance(item, dict):
                    entry = dict(item)
                else:
                    continue
                text = str(entry.get("text") or "").strip()
                term = str(entry.get("term") or "").strip()
                if not text and term:
                    text = term
                if not text:
                    continue
                data.append({
                    "id": str(entry.get("id") or ""),
                    "term": term or self._guess_term(text),
                    "text": text,
                    "desc": str(entry.get("desc") or entry.get("meaning") or "").strip(),
                    "usage": str(entry.get("usage") or "").strip(),
                    "aliases": [str(a).strip() for a in (entry.get("aliases") or []) if str(a).strip()],
                    "author": str(entry.get("author") or ""),
                    "author_name": str(entry.get("author_name") or ""),
                    "ts": str(entry.get("ts") or ""),
                })
        except Exception:
            self.log.exception("[meme_wiki] 读取梗库失败，按空库启动")
        return data

    def _save(self):
        out = []
        for entry in self._entries:
            if not entry.get("text"):
                continue
            out.append({
                "id": str(entry.get("id") or ""),
                "term": str(entry.get("term") or ""),
                "text": str(entry.get("text") or ""),
                "desc": str(entry.get("desc") or ""),
                "usage": str(entry.get("usage") or ""),
                "aliases": [str(a).strip() for a in (entry.get("aliases") or []) if str(a).strip()],
                "author": str(entry.get("author") or ""),
                "author_name": str(entry.get("author_name") or ""),
                "ts": str(entry.get("ts") or ""),
            })
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            if os.path.isfile(self._path):
                try:
                    shutil.copyfile(self._path, self._path + ".bak")
                except Exception:
                    pass
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
            return True
        except Exception:
            self.log.exception("[meme_wiki] 保存梗库失败")
            return False

    # ==================== 加梗解析 ====================
    @staticmethod
    def _clean(text):
        t = str(text or "").strip()
        t = re.sub(r"^(@\S+\s*)+", "", t)
        return t.strip(_EDGE)

    @staticmethod
    def _guess_term(text):
        m = re.match(r"^([^\s：:，,。；;]{1,16})[\s：:，,。；;]+", str(text or "").strip())
        return m.group(1).strip() if m else str(text or "").strip()[:16]

    @staticmethod
    def _parse_entry(body):
        """返回 (term, desc, usage, aliases, text)。"""
        body = str(body or "").strip()
        if not body:
            return None
        m = re.match(r"^([^\s：:，,。；;\n]{1,16})[\s：:，,。；;\n]+(.*)$", body, re.S)
        if m:
            term, rest = m.group(1).strip(), m.group(2).strip()
        else:
            term, rest = body, ""
        source = rest or body
        aliases = []
        am = re.search(r"(?:别名|关键词|触发词)\s*[：:]\s*(.*)$", source, re.S)
        if am:
            aliases = [a.strip() for a in re.split(r"[,，、/|;；\s]+", am.group(1)) if a.strip()]
            source = source[:am.start()].strip()
        usage = ""
        um = re.search(r"(?:接法|用法|怎么接|怎么用)\s*[：:]\s*(.*)$", source, re.S)
        if um:
            usage = um.group(1).strip()
            source = source[:um.start()].strip()
        desc = ""
        dm = re.search(r"(?:描述|含义|解释)\s*[：:]\s*(.*)$", source, re.S)
        if dm:
            desc = dm.group(1).strip()
        elif rest:
            desc = source.strip()
        return term, desc, usage, aliases, body

    # ==================== 召回 ====================
    def _query_text(self, text):
        m = _ASK.search(str(text or ""))
        if not m:
            return str(text or "").strip()
        head = str(text or "")[:m.start()].strip(_EDGE)
        head = re.sub(r"(这个梗|那个梗|这梗|那梗|这个|那个|到底|究竟)$", "", head).strip(_EDGE)
        head = head.strip("是").strip(_EDGE)
        return head if head and head not in _PRONOUN else str(text or "").strip()

    def _recall(self, text):
        q = _norm(self._query_text(text))
        if not q or q in _STOP:
            return []
        threshold = self._float("recall_threshold", 0.45)
        scored = []
        for entry in self._entries:
            term = _norm(entry.get("term") or "")
            body = _norm(entry.get("text") or "")
            score = 0.0
            for alias in entry.get("aliases") or []:
                a = _norm(alias)
                if not a:
                    continue
                if a == q:
                    score = max(score, 1.0)
                elif len(a) >= 2 and a in q:
                    score = max(score, 0.95)
                elif len(q) >= 2 and q in a:
                    score = max(score, 0.9)
            if term:
                if term == q:
                    score = max(score, 1.0)
                elif len(term) >= 2 and term in q:
                    score = max(score, 0.95)
                elif len(q) >= 2 and q in term:
                    score = max(score, 0.9)
            if score <= 0 and body:
                score = _coverage(q, body)
            if score >= threshold:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _score, entry in scored[:max(1, self._int("recall_top_k", 3))]]

    def _knowledge(self, entries):
        lines = []
        for idx, entry in enumerate(entries[:5], 1):
            term = str(entry.get("term") or "")
            desc = str(entry.get("desc") or "")
            usage = str(entry.get("usage") or "")
            aliases = [str(a) for a in (entry.get("aliases") or []) if str(a).strip()]
            text = str(entry.get("text") or "")
            lines.append(f"{idx}. {term}" if term else f"{idx}.")
            if aliases:
                lines.append(f"   别名：{'、'.join(aliases)}")
            if desc and usage:
                lines.append(f"   描述：{desc}")
                lines.append(f"   接法：{usage}")
            elif desc and desc != term and desc != text:
                lines.append(f"   资料：{desc}")
            elif usage:
                lines.append(f"   接法：{usage}")
            elif text and text != term:
                lines.append(f"   资料：{text}")
        return "\n".join(lines)

    # ==================== 角色回复（不是预设台词） ====================
    def _generate(self, text, entries, qq_context):
        group = str(qq_context.get("message_type") or "") == "group"
        group_name = str(qq_context.get("group_name") or "")
        nickname = str(qq_context.get("nickname") or qq_context.get("username") or "")
        meowid = str(qq_context.get("meowid") or qq_context.get("user_id") or "")
        base = ""
        try:
            if group:
                base = self.ctx.prompt().get_tool_prompt(meowid, text) or ""
            else:
                base = self.ctx.prompt().get_system_prompt(meowid, text) or ""
        except Exception:
            base = ""
        if not base:
            try:
                base = self.ctx.prompt().get_tool_prompt(meowid, text) or ""
            except Exception:
                base = ""
        if group:
            group_text = group_name or "这个群"
            who = nickname or "对方"
            scene = f"你在QQ群【{group_text}】聊天，刚才说话的是{who}。"
        else:
            scene = "你在QQ私聊。"
        block = self._knowledge(entries)
        system = (
            f"{base}\n\n{scene}\n\n"
            f"【梗库资料】\n{block}\n"
            f"要求：\n"
            f"1. 先判断对方这句话有没有用到上面的梗；没用到就不要硬提。\n"
            f"2. 用到了就接；接法里的句子可以直接照说，"
            f"不要为了显得自然硬改成别的说法。\n"
            f"3. 禁止念资料结构，禁止提“梗库/资料”，不要解释出处，不要逐条复述。"
        ).strip()
        messages = [{"role": "system", "content": system}]
        try:
            history = self.ctx.short_memory().load()
            limit = max(0, self._int("history_rounds", 6)) * 2
            for item in (history[-limit:] if limit else []):
                if isinstance(item, dict) and item.get("role") in ("user", "assistant") and item.get("content"):
                    messages.append({"role": item["role"], "content": str(item["content"])})
        except Exception:
            pass
        messages.append({"role": "user", "content": text})
        try:
            llm = self.ctx.llm()
            if not llm or not getattr(llm, "client", None):
                return ""
            resp = llm.chat(messages)
        except Exception:
            self.log.exception("[meme_wiki] 角色生成失败")
            return ""
        if not resp or not getattr(resp, "choices", None):
            return ""
        content = getattr(resp.choices[0].message, "content", "")
        return self._clean_reply(content)

    def _clean_reply(self, text):
        s = str(text or "").strip()
        s = re.sub(r"<think>.*?</think>", "", s, flags=re.S)
        s = re.sub(r"（[^）]*）|\([^)]*\)", "", s)
        s = re.sub(r"^\s*(【[^】]*】\s*[:：]?\s*)+", "", s)
        s = re.sub(r"^\s*[：:]\s*", "", s)
        s = s.strip().strip("\"'“”‘’「」『』")
        limit = self._int("max_reply_chars", 120)
        if limit > 0 and len(s) > limit:
            s = s[:limit].rstrip()
        return s.strip()

    def _send_reply(self, qq_context, reply):
        if not reply:
            return False
        parts = [p.strip() for p in re.split(r"[，。！？!?；;]", reply) if p.strip()]
        if not parts:
            parts = [reply]
        group = str(qq_context.get("message_type") or "") == "group"
        target = str(qq_context.get("target_id") or qq_context.get("group_id") or qq_context.get("user_id") or "")
        if not target:
            return False
        limit = self._int("max_reply_chars", 120)
        sent = False
        for idx, part in enumerate(parts):
            if limit > 0 and len(part) > limit:
                part = part[:limit]
            try:
                if group:
                    uid = str(qq_context.get("user_id") or "")
                    if idx == 0 and uid and self._bool("reply_with_at", False):
                        self.ctx.napcat().send_group_at_text(target, uid, part)
                    else:
                        self.ctx.napcat().send_group_text(target, part)
                else:
                    self.ctx.napcat().send_private_text(target, part)
                sent = True
            except Exception:
                self.log.exception("[meme_wiki] 发送失败")
        return sent

    def _remember(self, text, reply, qq_context):
        if not self._bool("write_memory", True):
            return
        try:
            sm = self.ctx.short_memory()
            group = str(qq_context.get("message_type") or "") == "group"
            type_ = "qq_groupchat" if group else "qq_response"
            rounds = 10 if group else 20
            if group:
                content = f"【来自QQ，{qq_context.get('group_name') or '群'}的群消息】{text}"
            else:
                content = f"【来自QQ，{qq_context.get('nickname') or '对方'}的消息】{text}"
            sm.save({"role": "user", "content": content, "type": type_}, rounds)
            sm.save({"role": "assistant", "content": reply, "type": type_}, rounds)
        except Exception:
            self.log.exception("[meme_wiki] 写短期记忆失败")

    # ==================== 命令 ====================
    def _add(self, body, qq_context, nickname):
        uid = str(qq_context.get("user_id") or "")
        if not self._can_add(uid):
            self._send_text(qq_context, "没有添加梗的权限。")
            return
        parsed = self._parse_entry(body)
        if not parsed:
            self._send_text(qq_context, self._help())
            return
        term, desc, usage, aliases, text = parsed
        if len(term) > 32:
            self._send_text(qq_context, "梗名太长了，控制在 32 字以内。")
            return
        limit = self._int("max_desc_chars", 500)
        if limit > 0 and len(text) > limit:
            text = text[:limit]
        key = _norm(text)
        term_key = _norm(term)
        saved = True
        full = False
        index = -1
        with self._lock:
            index = next((
                i for i, e in enumerate(self._entries)
                if (term_key and _norm(e.get("term")) == term_key)
                or _norm(e.get("text")) == key
            ), -1)
            max_entries = self._int("max_entries", 5000)
            if index < 0 and max_entries > 0 and len(self._entries) >= max_entries:
                full = True
            else:
                entry = {
                    "id": f"m_{int(time.time() * 1000)}_{len(self._entries)}",
                    "term": term,
                    "text": text,
                    "desc": desc,
                    "usage": usage,
                    "aliases": aliases,
                    "author": uid,
                    "author_name": str(nickname or qq_context.get("nickname") or ""),
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                if index >= 0:
                    self._entries[index] = entry
                else:
                    self._entries.append(entry)
                saved = self._save()
        if full:
            self._send_text(qq_context, f"梗库满了（{self._int('max_entries', 5000)} 条），先删几条吧。")
            return
        if not saved:
            self._send_text(qq_context, "保存失败，先看日志。")
            return
        tip = f"已{'更新' if index >= 0 else '记下'}「{term}」"
        if desc:
            tip += f"\n描述：{desc}"
        if usage:
            tip += f"\n接法：{usage}"
        if aliases:
            tip += f"\n别名：{'、'.join(aliases)}"
        self._send_text(qq_context, tip)

    def _delete(self, term, qq_context):
        uid = str(qq_context.get("user_id") or "")
        if not self._admin(uid):
            self._send_text(qq_context, "删除梗只有管理员可用（配置 admin_qqs）。")
            return
        term = _norm(term)
        if not term:
            self._send_text(qq_context, "用法：Meowlisis梗删除 <词>")
            return
        saved = False
        removed = None
        with self._lock:
            for i, entry in enumerate(self._entries):
                if _norm(entry.get("term")) == term:
                    removed = self._entries.pop(i)
                    saved = self._save()
                    break
        if not removed:
            self._send_text(qq_context, f"没有「{term}」这条梗。")
            return
        if not saved:
            self._send_text(qq_context, "删除失败，先看日志。")
            return
        self._send_text(qq_context, f"已删除「{removed.get('term') or term}」。")

    def _export(self, qq_context, word=""):
        with self._lock:
            rows = list(self._entries)
        if word:
            w = _norm(word)
            rows = [e for e in rows if w in _norm(
                f"{e.get('term')} {e.get('text')} {e.get('desc')} {e.get('usage')} "
                f"{' '.join(e.get('aliases') or [])}")]
            if not rows:
                self._send_text(qq_context, f"没有匹配「{word}」的梗。")
                return
        if not rows:
            self._send_text(qq_context, "梗库还是空的。用 Meowlisis梗 <词> 描述：... 接法：... 加一条。")
            return
        rows.sort(key=lambda e: str(e.get("ts") or ""), reverse=True)
        lines = ["# Meowlisis 梗库", "", f"共 {len(rows)} 条", ""]
        for entry in rows:
            term = str(entry.get("term") or "")
            desc = str(entry.get("desc") or "")
            usage = str(entry.get("usage") or "")
            aliases = [str(a) for a in (entry.get("aliases") or []) if str(a).strip()]
            text = str(entry.get("text") or "")
            if desc and usage:
                lines.append(f"- **{term}**：{desc}")
                lines.append(f"  - 接法：{usage}")
            elif desc and desc != term and desc != text:
                lines.append(f"- **{term}**：{desc}")
            elif usage:
                lines.append(f"- **{term}**：接法：{usage}")
            elif text and text != term:
                lines.append(f"- **{term}**：{text}")
            else:
                lines.append(f"- **{term}**")
            if aliases:
                lines.append(f"  - 别名：{'、'.join(aliases)}")
        md = "\n".join(lines)
        try:
            out_dir = os.path.join(self._base, "exports")
            os.makedirs(out_dir, exist_ok=True)
            name = "Meowlisis梗库.md"
            if word:
                safe = re.sub(r'[\\/:*?"<>|\s]+', "_", str(word))[:20] or "筛选"
                name = f"Meowlisis梗库_{safe}.md"
            path = os.path.join(out_dir, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
            self.log.info(f"[meme_wiki] 梗库 md 已导出: {path}")
        except Exception:
            self.log.exception("[meme_wiki] 导出 md 失败")
            self._send_text(qq_context, md[:1500])
            return
        if not self._send_file(qq_context, path):
            self._send_text(qq_context, md[:1500])

    def _send_file(self, qq_context, path):
        group = str(qq_context.get("message_type") or "") == "group"
        target = str(qq_context.get("target_id") or qq_context.get("group_id") or qq_context.get("user_id") or "")
        if not target or not os.path.isfile(path):
            return False
        try:
            if group:
                self.ctx.napcat().send_group_file(target, path)
            else:
                resp = self.ctx.napcat().call_action_sync("upload_private_file", {
                    "user_id": int(target),
                    "file": path,
                    "name": os.path.basename(path),
                })
                if isinstance(resp, dict) and resp.get("retcode") not in (0, "0", None):
                    self.log.warning(f"[meme_wiki] 私聊文件发送失败: {resp}")
                    return False
            return True
        except Exception:
            self.log.exception("[meme_wiki] 发送文件失败")
            return False

    def _send_text(self, qq_context, text):
        if not text:
            return False
        group = str(qq_context.get("message_type") or "") == "group"
        target = str(qq_context.get("target_id") or qq_context.get("group_id") or qq_context.get("user_id") or "")
        if not target:
            return False
        try:
            if group:
                self.ctx.napcat().send_group_text(target, text)
            else:
                self.ctx.napcat().send_private_text(target, text)
            return True
        except Exception:
            self.log.exception("[meme_wiki] 发送失败")
            return False

    def _cool(self, qq_context):
        key = "{}:{}".format(
            qq_context.get("message_type") or "private",
            qq_context.get("target_id") or qq_context.get("group_id") or qq_context.get("user_id") or "",
        )
        seconds = self._int("cooldown_seconds", 8)
        now = time.time()
        if seconds > 0 and now - self._last_reply.get(key, 0.0) < seconds:
            return True
        self._last_reply[key] = now
        return False

    def _help(self):
        add = str(self.config.get("add_prefix", "Meowlisis梗"))
        query = str(self.config.get("query_prefix", "Meowlisis查梗"))
        return (
            "Meowlisis 梗库：\n"
            f"{add} <词> 描述：... 接法：...   记梗\n"
            f"{add} help                        本帮助\n"
            f"{query}                         导出全部梗（Markdown 文件）\n"
            f"{query} <词>                    只看匹配的梗\n"
            f"{add}删除 <词>                  删除（管理员）"
        )

    # ==================== QQ 入口 ====================
    def route_qq(self, text, qq_context=None, nickname=""):
        try:
            if not self._bool("enabled", True):
                return False
            t = self._clean(text)
            if not t:
                return False
            qq_context = qq_context or {}

            for alias in ("Meowlisis导出", "Meowlisis 导出", "Meowlisis列表", "Meowlisis 列表"):
                if t == alias or t.startswith(alias + " "):
                    self._export(qq_context)
                    return True

            for add_prefix in self._add_prefixes():
                if not t.startswith(add_prefix):
                    continue
                body = t[len(add_prefix):].strip().strip(_EDGE)
                if body in ("help", "帮助", "?", "？", "指令", "用法", "说明"):
                    self._send_text(qq_context, self._help())
                    return True
                if body.startswith(("导出", "export", "md", "MD")):
                    self._export(qq_context)
                    return True
                if body in ("列表", "list", "清单"):
                    self._export(qq_context)
                    return True
                if body.startswith("删除") or body.startswith("删 "):
                    body = re.sub(r"^删(除)?\s*", "", body).strip().strip(_EDGE)
                    self._delete(body, qq_context)
                    return True
                if not body:
                    self._send_text(qq_context, self._help())
                    return True
                self._add(body, qq_context, nickname)
                return True

            for query_prefix in self._query_prefixes():
                if not t.startswith(query_prefix):
                    continue
                word = t[len(query_prefix):].strip().strip(_EDGE)
                self._export(qq_context, word)
                return True

            # 普通消息：召回 → 交给角色生成
            entries = self._recall(t)
            if not entries:
                return False
            if self._cool(qq_context):
                return False
            reply = self._generate(t, entries, qq_context)
            if not reply:
                return False
            if not self._send_reply(qq_context, reply):
                return False
            self._remember(t, reply, qq_context)
            return True
        except Exception:
            try:
                self.log.exception("[meme_wiki] route_qq 异常")
            except Exception:
                pass
            return False

    def _add_prefixes(self):
        base = str(self.config.get("add_prefix", "Meowlisis梗"))
        aliases = [base]
        if base == "Meowlisis梗":
            aliases += ["Meowlisis 梗", "喵呜梗"]
        return aliases

    def _query_prefixes(self):
        base = str(self.config.get("query_prefix", "Meowlisis查梗"))
        aliases = [base]
        if base == "Meowlisis查梗":
            aliases += ["Meowlisis 查梗", "查梗", "/梗"]
        else:
            aliases += ["/梗", "查梗"]
        return aliases


PLUGIN = Plugin()
