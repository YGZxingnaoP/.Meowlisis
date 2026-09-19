# -*- coding: utf-8 -*-
import os
import re
import time
import datetime
from typing import List, Dict

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.port.deepseek import MeowAbstractDeepSeekLLM
from func.catbrain.AbstractMem.port.aliyun import MeowAbstractAliyunLLM
from func.catbrain.AbstractMem.record.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.process.tag_store import MeowTagStore
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory
from func.catbrain.AbstractMem.process.dedup import MeowDedup
from func.catbrain.AbstractMem.process.archive import MeowArchive


class MeowUpdateAbstractMemory:
    """摘要更新类：归类、范围内检索、判定加强削弱或新建并写入 meow-YYMM.json"""

    def __init__(self):
        """初始化工具、加载器、更新器与归档器"""
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.summary_tool = MeowSummaryTool()
        self.tag_store = MeowTagStore()
        self.llm = None
        self._loader = MeowLoadAbstractMemory()
        self._dedup = MeowDedup()
        self._archive = MeowArchive()
        self._last_philosophy_trigger = 0.0

    def _ensure_llm(self):
        """懒加载摘要独立 LLM 客户端"""
        if self.llm is None:
            self.llm = self._create_llm()
        return self.llm

    def _create_llm(self):
        """按配置创建摘要独立 LLM 客户端"""
        if self.config.abstract_llm_type == "gemini":
            from func.catbrain.AbstractMem.port.gemini import MeowAbstractGeminiLLM
            return MeowAbstractGeminiLLM()
        if self.config.abstract_llm_type == "aliyun":
            return MeowAbstractAliyunLLM()
        return MeowAbstractDeepSeekLLM()

    def _get_character_prompt(self) -> str:
        """获取角色卡与价值观提示词"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            return SystemPromptBridge().get_persona_prompt() or ""
        except Exception:
            return ""

    def _load_instruction(self) -> str:
        """读取摘要指令提示词文件"""
        path = os.path.join("func", "catbrain", "AbstractMem", "record", "summary_prompt.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            self.log.exception("读取摘要指令失败")
            return "请以第一人称客观概括以下对话记忆，每个事件调用一次 save_memory_summary 工具。"

    def _extract_joint(self, content: str) -> List[str]:
        """从对话内容中提取参与用户名"""
        ai_name = AppConfig().ai_name or "喵呜"
        names = re.findall(r'\]\[([^\]]+)\]:', content)
        joint = []
        for n in names:
            n = n.strip()
            if n and n != ai_name and n not in joint:
                joint.append(n)
        return joint

    def _recent_memory_hint(self, data) -> str:
        """构建近期已记忆要点附件"""
        lines = int(self.config.summary_recent_memory_lines or 0)
        if lines <= 0 or not data:
            return ""
        items = [d for d in data if isinstance(d, dict) and d.get("event")]
        if not items:
            return ""
        items = items[-lines:]
        return "【近期已记忆要点】\n" + "\n".join(f"- {d.get('event')}" for d in items)

    def _build_messages(self, content: str, data=None) -> List[Dict]:
        """构建概括消息：摘要指令 + 角色提示词 + tags附件 + 近期记忆 + 待概括内容"""
        instruction = self._load_instruction().format(
            ai_name=AppConfig().ai_name,
            max_events=int(self.config.summary_max_events or 0) or 10,
        )
        system_text = instruction
        character_prompt = self._get_character_prompt()
        if character_prompt:
            system_text += "\n\n【角色提示词】\n" + character_prompt
        messages = [{"role": "system", "content": system_text}]
        tags_attachment = self.summary_tool.build_tags_attachment()
        if tags_attachment:
            messages.append({"role": "user", "content": tags_attachment})
        recent_hint = self._recent_memory_hint(data)
        if recent_hint:
            messages.append({"role": "user", "content": recent_hint})
        messages.append({"role": "user", "content": f"待概括的对话记录：\n{content}"})
        return messages

    def _normalize_tags(self, tags) -> List[str]:
        """规范化 tags：去空去重并限制上限"""
        if not isinstance(tags, list):
            return []
        result = []
        for t in tags:
            t = str(t).strip()
            if t and t not in result:
                result.append(t)
            if len(result) >= self.config.summary_tags_limit:
                break
        return result

    def _normalize_topics(self, topics) -> List[str]:
        """规范化 topics：仅保留限定话题"""
        if isinstance(topics, str):
            topics = [topics]
        result = []
        for t in (topics or []):
            t = str(t).strip()
            if t in self.summary_tool.TOPICS and t not in result:
                result.append(t)
        return result if result else ["日常"]

    def _normalize_accuracy(self, accuracy) -> int:
        """规范化 accuracy 到 1/3/5 三档"""
        try:
            a = int(accuracy)
        except (TypeError, ValueError):
            return 5
        if a <= 1:
            return 1
        if a <= 3:
            return 3
        return 5

    def _normalize_number(self, value, minimum, maximum) -> float:
        """规范化数值到区间内"""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return float(minimum)
        if v < minimum:
            return float(minimum)
        if v > maximum:
            return float(maximum)
        return v

    def _normalize_joint(self, joint, content) -> List[str]:
        """规范化 joint：清洗后为空则程序化提取"""
        if isinstance(joint, str):
            joint = [joint]
        ai_name = AppConfig().ai_name or "喵呜"
        result = []
        for n in (joint or []):
            n = str(n).strip()
            if n and n != ai_name and n not in result:
                result.append(n)
        if not result:
            result = self._extract_joint(content)
        return result

    def _clean_text(self, text: str) -> str:
        """清洗事件文本前缀"""
        if not text:
            return ""
        ai = AppConfig().ai_name or "喵呜"
        patterns = [
            r'^(好的|好|嗯+|哈哈+|嘿嘿+)[，。！？、,.!?\s]*',
            rf'^(我是|我是{re.escape(ai)}|{re.escape(ai)})[，。！？、,.!?\s]*',
        ]
        prev = None
        while prev != text and text:
            prev = text
            for p in patterns:
                text = re.sub(p, '', text, count=1)
        return text.strip()

    def _normalize_event(self, event: Dict, content: str) -> Dict:
        """规范化单个事件的字段"""
        event["event"] = self._clean_text(event.get("event", ""))
        event["tags"] = self._normalize_tags(event.get("tags"))
        event["topics"] = self._normalize_topics(event.get("topics"))
        event["joint"] = self._normalize_joint(event.get("joint"), content)
        event["importance"] = self._normalize_number(event.get("importance"), 0, 10)
        event["accuracy"] = self._normalize_accuracy(event.get("accuracy"))
        return event

    @staticmethod
    def _scope(event: Dict, data: List[Dict]) -> List[Dict]:
        """筛出话题命中且标签包含的已有记忆"""
        topics = set(event.get("topics") or [])
        tags = {str(t).strip() for t in (event.get("tags") or []) if str(t).strip()}
        if not topics:
            return []
        scope = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if not (topics & set(item.get("topics") or [])):
                continue
            item_tags = {str(t).strip() for t in (item.get("tags") or []) if str(t).strip()}
            if tags and item_tags and not (tags & item_tags):
                continue
            scope.append(item)
        return scope

    @staticmethod
    def _render(items: List[Dict], limit: int = 0) -> str:
        """把记忆条目渲染成文本供模型查看"""
        rows = items[:limit] if limit and limit > 0 else items
        lines = []
        for item in rows:
            topics = "、".join(item.get("topics") or [])
            tags = "、".join(item.get("tags") or [])
            lines.append(f"{item.get('id', '')} | {item.get('time', '')} | 话题:{topics} | 标签:{tags} | {item.get('event', '')}")
        return "\n".join(lines)

    def _scope_reply(self, scope: List[Dict]) -> str:
        """生成范围内候选记忆回复"""
        if not scope:
            return "该话题与标签范围内没有已有记忆，请调用 judge_memory_relation 以 action=new 新建"
        cap = self._render_cap()
        text = self._render(scope, cap)
        if len(scope) > cap:
            text += f"\n（范围内共 {len(scope)} 条，此处仅列出前 {cap} 条，其余请用 grep_memories 按关键词检索）"
        return "该话题与标签范围内的已有记忆：\n" + text

    def _render_cap(self) -> int:
        """返回候选回传条数上限"""
        return int(self.config.summary_scope_reply_limit or 0) or 80

    @staticmethod
    def _grep(scope: List[Dict], keyword) -> List[Dict]:
        """在限定范围内按关键词匹配事件内容"""
        k = str(keyword or "").strip()
        if not k:
            return list(scope)
        return [item for item in scope if k in str(item.get("event") or "")]

    def _run_flow(self, llm, content: str, data: List[Dict], index: Dict,
                  now_str: str, now_iso: str):
        """工具循环：归类、范围内检索、判定加强削弱或新建"""
        messages = self._build_messages(content, data)
        tools = (self.summary_tool.build_tools()
                 + self.summary_tool.build_grep_tool()
                 + self.summary_tool.build_judge_tool())
        grep_limit = int(self.config.summary_grep_limit or 0) or 10
        max_rounds = int(self.config.summary_tool_rounds or 0) or 80
        render_cap = self._render_cap()
        events, pending = [], []
        lookup = dict(index)
        scope, current, grep_used, completed, save_reject = [], None, 0, False, 0
        for _ in range(max_rounds):
            resp = llm.chat(messages, tools=tools)
            if not resp or not resp.choices:
                break
            msg = resp.choices[0].message
            tool_calls = msg.tool_calls or []
            if not tool_calls:
                completed = True
                break
            messages.append({
                "role": "assistant",
                "content": msg.content or None,
                "reasoning_content": getattr(msg, "reasoning_content", "") or "",
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                               for tc in tool_calls]
            })
            for tc in tool_calls:
                name = tc.function.name
                args = self.summary_tool.parse_arguments(tc.function.arguments)
                reply = "已忽略"
                if name == self.summary_tool.TOOL_NAME:
                    if current is not None and save_reject < 2:
                        save_reject += 1
                        reply = "请先调用 judge_memory_relation 判定上一条事件，再输出新的概括"
                    else:
                        if current is not None:
                            current["action"] = "new"
                            scope, current, grep_used = [], None, 0
                        save_reject = 0
                        event = self._register_event(args, content)
                        if event is None:
                            reply = "参数不合法，请重新调用工具"
                        else:
                            event["time"] = now_str
                            event["id"] = self._dedup.make_id(event)
                            events.append(event)
                            exist = lookup.get(event["id"])
                            if exist is not None:
                                self._dedup._apply_same(exist, event, now_iso)
                                event["action"] = "origin"
                                scope, current, grep_used = [], None, 0
                                reply = "该事件与已有记忆完全一致，已加强"
                            else:
                                scope = self._scope(event, data + pending)
                                pending.append(event)
                                lookup[event["id"]] = event
                                current, grep_used = event, 0
                                event["action"] = "new"
                                reply = self._scope_reply(scope)
                elif name == self.summary_tool.GREP_TOOL_NAME:
                    if current is None:
                        reply = "请先调用 save_memory_summary 提供事件与归类"
                    elif grep_used >= grep_limit:
                        reply = "检索次数已达上限，请直接判定"
                    else:
                        grep_used += 1
                        hits = self._grep(scope, (args or {}).get("keyword"))
                        reply = self._render(hits, render_cap) if hits else "未检索到相关记忆"
                elif name == self.summary_tool.JUDGE_TOOL_NAME:
                    if current is None:
                        reply = "请先调用 save_memory_summary 提供事件与归类"
                    else:
                        reply = self._apply_judge(args, current, lookup, scope, now_iso)
                        current = None
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": reply})
        return events, completed

    def _register_event(self, args, content: str):
        """校验并规范化一个事件参数"""
        if not isinstance(args, dict) or not str(args.get("event") or "").strip():
            return None
        event = self._normalize_event(dict(args), content)
        if not event.get("event"):
            return None
        return event

    def _apply_judge(self, args, current: Dict, lookup: Dict, scope: List[Dict], now_iso: str) -> str:
        """应用判定工具结果：加强、削弱或新建"""
        action = str((args or {}).get("action") or "new")
        target_id = str((args or {}).get("target_id") or "")
        target = lookup.get(target_id)
        if target is not None and not any(t is target for t in scope):
            target = None
        if action == "strengthen" and target is not None:
            self._dedup._apply_same(target, current, now_iso)
            current["action"] = "origin"
            return "已加强"
        if action == "weaken" and target is not None:
            self._dedup._apply_opposite(target, now_iso)
            current["action"] = "weaken"
            return "已削弱"
        current["action"] = "new"
        return "已按新建处理"

    def _trigger_values_update(self):
        """哲思话题触发价值观更新"""
        cooldown = self.config.values_philosophy_cooldown_minutes * 60
        now = time.time()
        if now - self._last_philosophy_trigger < cooldown:
            self.log.info("哲思触发价值观更新处于冷却期，跳过")
            return
        self._last_philosophy_trigger = now
        try:
            from func.pipeline.llm_values import MeowLLMValuesBridge
            MeowLLMValuesBridge().trigger_update("哲思话题触发")
        except Exception:
            self.log.exception("触发价值观更新失败")

    def summarize(self, content: str, rounds: int) -> bool:
        """触发概括：工具驱动归类检索判定后写入并归档扫描"""
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            self.log.error("摘要 LLM 不可用，跳过概括")
            return False
        data = self._loader.load()
        index = {item.get("id"): item for item in data if isinstance(item, dict) and item.get("id")}
        now = datetime.datetime.now()
        now_str = now.strftime("%Y-%m-%d-%H-%M")
        now_iso = now.isoformat(timespec="seconds")
        events, completed = self._run_flow(llm, content, data, index, now_str, now_iso)
        if not events:
            if not completed:
                self.log.error("摘要流程未正常结束，保留原文重试")
                return False
            self.log.info("摘要判定无需记忆")
            return True
        new_events = []
        changed = False
        for event in events:
            action = event.pop("action", "new")
            if action == "new":
                self._dedup._init_evidence(event, now_iso)
                new_events.append(event)
            else:
                changed = True
        if new_events:
            data.extend(new_events)
            self.tag_store.append([t for e in new_events for t in (e.get("tags") or [])])
        if new_events or changed:
            self._loader.save(data)
        for event in events:
            if "哲思" in (event.get("topics") or []):
                self._trigger_values_update()
                break
        try:
            self._archive.scan()
        except Exception:
            self.log.exception("归档扫描失败")
        return True
