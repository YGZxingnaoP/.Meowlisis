# -*- coding: utf-8 -*-
import json
import re
from types import SimpleNamespace

from func.log.default_log import DefaultLog
from func.toolbox.flux_painter.port.base import create_painter_llm
from func.toolbox.flux_painter.prompts import get_prompt_spec

LAW_TOOL_NAMES = ("law_index", "law_search", "law_read", "danbooru_tag")

class TBPromptProducer:
    """需求→{title, positive, reply, canvas}：深度思考+function calling，法典按需检索注入"""

    def __init__(self, config):
        """初始化。"""
        self.config = config
        self.log = DefaultLog().getLogger()
        self._port = None
        self._knowledge = {}
        self._spec_cache = None

    @property
    def spec(self):
        """当前底模家族的提示词规范（配置热重载切家族时自动跟着换）"""
        family = getattr(self.config, "family", "anima")
        if self._spec_cache is None or self._spec_cache.family != family:
            self._spec_cache = get_prompt_spec(family)
        return self._spec_cache

    @property
    def knowledge(self):
        """当前家族的提示词法典（anima / moss 各一份，互不污染）"""
        spec = self.spec
        k = self._knowledge.get(spec.family)
        if k is None:
            k = spec.knowledge_cls(self.config)
            self._knowledge[spec.family] = k
        return k

    def _llm(self):
        """懒加载提示词 LLM 端口"""
        if self._port is None:
            self._port = create_painter_llm(self.config)
        return self._port

    def _chat_once(self, port, messages, on_stream=None, tools=None):
        """调用模型（on_stream 时走流式并逐段回调，否则非流式），返回 message-like 或 None"""
        thinking = bool(getattr(self.config, "thinking_enabled", True))
        spec = self.spec
        choice = None if thinking else PRODUCE_TOOL_CHOICE
        if on_stream is None:
            resp = port.chat(messages, tools=(tools or [spec.tool]), tool_choice=choice,
                             enable_thinking=thinking)
            if resp is None or not resp.choices:
                return None
            return resp.choices[0].message
        reasoning_parts, content_parts = [], []
        tool_calls = {}
        got = False
        try:
            stream = port.chat_stream(messages, tools=(tools or [spec.tool]),
                                      tool_choice=choice, enable_thinking=thinking)
            for chunk in stream or []:
                got = True
                try:
                    choices = chunk.choices or []
                    if not choices:
                        continue
                    delta = choices[0].delta
                except Exception:
                    continue
                r = getattr(delta, "reasoning_content", None) or ""
                c = getattr(delta, "content", None) or ""
                if r:
                    reasoning_parts.append(r)
                    if on_stream and (len("".join(reasoning_parts)) % 24 < len(r) or len(reasoning_parts) < 2):
                        on_stream(r)
                if c:
                    content_parts.append(c)
                    if on_stream:
                        on_stream(c)
                for dc in (getattr(delta, "tool_calls", None) or []):
                    def _f(obj, key, default=None):
                        """取浮点配置（非法值回落默认）。"""
                        if isinstance(obj, dict):
                            return obj.get(key, default)
                        return getattr(obj, key, default)

                    try:
                        idx = _f(dc, "index")
                        idx = 0 if idx is None else int(idx)
                    except Exception:
                        idx = 0
                    slot = tool_calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                    cid = _f(dc, "id")
                    if cid:
                        slot["id"] = str(cid)
                    fn = _f(dc, "function")
                    if fn:
                        name = _f(fn, "name")
                        if name:
                            slot["name"] = str(name)
                        args = _f(fn, "arguments")
                        if args:
                            slot["args"] += str(args)
        except Exception:
            self.log.exception("[flux_painter] 提示词流式调用异常")
            return None
        if not got:
            return None
        tcs = None
        if tool_calls:
            named = {i: s for i, s in tool_calls.items() if s["name"]}
            if not named:
                self.log.warning("[flux_painter] 流式工具调用缺 name，改走非流式")
                resp = port.chat(messages, tools=(tools or [spec.tool]), tool_choice=choice,
                                 enable_thinking=thinking)
                if resp is not None and resp.choices:
                    return resp.choices[0].message
            tcs = [SimpleNamespace(id=slot["id"] or f"c{i}", type="function",
                                   function=SimpleNamespace(name=slot["name"],
                                                            arguments=slot["args"] or "{}"))
                   for i, slot in sorted(named.items())]
        return SimpleNamespace(
            reasoning_content="".join(reasoning_parts) or None,
            content="".join(content_parts) or None,
            tool_calls=tcs)

    def _extract_call(self, message):
        """从响应提取 produce_painting 参数 dict，无则空 dict"""
        for tc in getattr(message, "tool_calls", None) or []:
            fn = getattr(tc, "function", None)
            if fn and fn.name == "produce_painting":
                try:
                    args = json.loads(fn.arguments or "{}")
                    return args if isinstance(args, dict) else {}
                except Exception:
                    return {}
        content = str(getattr(message, "content", None) or "")
        m = re.search(r"\{[\s\S]*\"title\"[\s\S]*\}", content)
        if m:
            try:
                data = json.loads(m.group(0))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    LAW_TOOL_NAMES = LAW_TOOL_NAMES      # 类内直接引用模块常量（含 danbooru_tag）

    def _run_tool(self, name, args):
        """执行检索类工具（法典 / danbooru），返回喂回给 LLM 的文本"""
        try:
            if name == "danbooru_tag":
                from func.toolbox.flux_painter.prompts.danbooru_tool import run as run_db
                return run_db(args, config=self.config, log=self.log)
            if name == "law_index":
                txt = self.knowledge.index()
                kw = str((args or {}).get("keyword") or "").strip()
                if kw:
                    hit = [ln for ln in txt.splitlines() if kw in ln]
                    txt = ("\n".join(hit) if hit
                           else ("（目录中无标题含「%s」的章节，以下是完整目录）\n" % kw) + txt)
                return txt[:6000]
            if name == "law_search":
                q = str((args or {}).get("query") or "").strip()
                try:
                    top = int((args or {}).get("top") or 3)
                except Exception:
                    top = 3
                return self.knowledge.search(q, top=max(1, min(top, 3)), per_limit=800)
            if name == "law_read":
                return self.knowledge.read(str((args or {}).get("section") or "").strip())
        except Exception:
            self.log.exception("[flux_painter] 法典工具执行异常")
            return "（法典工具执行失败，请依据已有信息直接产出）"
        return f"（未知工具 {name}）"

    def _tool_loop(self, port, messages, on_stream=None, max_rounds=8):
        """先让 LLM 自主翻阅法典（仅提供检索工具的家族），再产出 produce_painting。"""
        spec = self.spec
        law_tools = list(getattr(spec, "law_tools", ()) or ())
        law_budget = int(getattr(spec, "law_budget", 0) or 0)
        asked = 0
        used = 0
        while True:
            allow_retrieval = (law_tools and used < law_budget and asked < 2)
            tools = ([spec.tool] + law_tools) if allow_retrieval else [spec.tool]
            message = self._chat_once(port, messages, on_stream=on_stream, tools=tools)
            if message is None:
                return None
            tcs = list(getattr(message, "tool_calls", None) or [])
            names = [(getattr(getattr(tc, "function", None), "name", "") or "").strip()
                     for tc in tcs]
            law_calls = [tc for tc, nm in zip(tcs, names) if nm in self.LAW_TOOL_NAMES]
            if ("produce_painting" in names) or (not law_calls) or asked >= max_rounds:
                return message
            messages.append({
                "role": "assistant",
                "content": str(getattr(message, "content", None) or ""),
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name,
                                             "arguments": tc.function.arguments or "{}"}}
                               for tc in tcs],
            })
            for tc in law_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                result = self._run_tool(tc.function.name, args)
                used += len(result)
                self.log.info(f"[flux_painter] 检索自检 {tc.function.name} -> {len(result)} 字符"
                              f"（累计 {used}）")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            asked += 1
            messages.append({
                "role": "user",
                "content": "（系统提示）检索到此为止，请立即调用 produce_painting 产出画作要素。"})

    def run(self, user_text, nickname="", persona="", on_stream=None,
            role_card=None, memory=None, base_elements=None, base_request="",
            reference_image=None):
        """生成画作要素，成功返回 dict，失败返回 None；on_stream(文本) 实时回提示词片段"""
        port = self._llm()
        if port is None or not getattr(port, "client", None):
            self.log.error("[flux_painter] 提示词 LLM 不可用")
            return None
        spec = self.spec
        system = spec.build_system(self.config, self.knowledge, user_text,
                                  persona=persona, role_card=role_card)
        messages = [{"role": "system", "content": system}]
        budget = 9000
        for m in (memory or [])[:12]:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "")
            if role not in ("user", "assistant"):
                continue
            content = str(m.get("content") or "")[:500].strip()
            if not content:
                continue
            budget -= len(content) + 24
            if budget <= 0:
                break
            messages.append({"role": role, "content": content})
        ref_part = self._reference_part(reference_image)
        if base_elements:
            user_content = spec.rework_hint(base_elements).format(
                title=str(base_elements.get("title") or ""),
                request=str(base_request or ""),
                positive=str(base_elements.get("positive") or ""),
                cinema=str(base_elements.get("cinema") or ""),
                layout=str(base_elements.get("layout") or ""),
                character=str(base_elements.get("character") or ""),
                user_text=user_text)
            messages.append({"role": "user", "content": self._user_content(user_content, ref_part)})
        else:
            variety = ("（姿势与构图由你决定，可参考法典但不要照搬，"
                       "也别每次都写跪/趴/躺，按需求自然选。）")
            messages.append({"role": "user",
                             "content": self._user_content(
                                 f"（{nickname}）：{user_text}\n\n{variety}", ref_part)})
        for attempt in (1, 2):
            try:
                message = self._tool_loop(port, messages, on_stream=on_stream)
                if message is None:
                    self.log.warning(f"[flux_painter] 提示词生成无返回(第{attempt}次)")
                    if attempt == 1:
                        messages.append({"role": "user",
                                         "content": "（系统提示）请重新调用 produce_painting 完成产出。"})
                    continue
                data = self._extract_call(message)
                if not data:
                    snippet = str(getattr(message, "content", None) or "")[:200]
                    tcs = [(getattr(getattr(tc, "function", None), "name", "") or "")
                   for tc in (getattr(message, "tool_calls", None) or [])]
                    self.log.warning(f"[flux_painter] 未解析到正向提示词(第{attempt}次) "
                                     f"tool_calls={tcs} content={snippet!r}")
                    if attempt == 1:
                        messages.append({"role": "user",
                                         "content": "（系统纠正）没有收到 produce_painting 调用："
                                                    "请按 schema 重新调用一次完成产出。"})
                    continue
                issues = spec.issues(data)
                if issues:
                    code, msg = issues[0]
                    self.log.warning(f"[flux_painter] 提示词校验未过({code})(第{attempt}次)")
                    if attempt == 1:
                        messages.append({"role": "user", "content": msg})
                        continue
                    if code in ("missing_positive", "missing_caption"):
                        continue
                data = spec.normalize(data, self.config)
                return data
            except Exception:
                self.log.exception(f"[flux_painter] 提示词生成异常(第{attempt}次)")
        return None



    @classmethod


    @staticmethod
    def _reference_part(reference_image):
        """参考图 → 多模态消息片段；无图或读不出时返回 None"""
        if not reference_image:
            return None
        try:
            from func.toolbox.flux_painter.img2img.ref_source import image_data_url
            url = image_data_url(str(reference_image))
        except Exception:
            url = ""
        if not url:
            return None
        return {"type": "image_url", "image_url": {"url": url}}

    @staticmethod
    def _user_content(text, ref_part):
        """用户消息：无参考图时就是纯文本；有图时附一段说明 + 图片本体"""
        if not ref_part:
            return text
        return [
            {"type": "text", "text": str(text or "")},
            {"type": "text",
             "text": "【参考图】这是用户要画的那块内容：主体、构图、配色、场景以它为准，"
                     "positive / cinema 要能让绘画模型把这块内容画成一张完整插画。"},
            ref_part,
        ]
