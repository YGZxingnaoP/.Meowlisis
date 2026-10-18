import os
import json
import re
from threading import Thread, Lock, Event

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.tools.singleton_mode import singleton
from func.psyche.config import MeowPsycheConfig
from func.psyche.psyche_tool import MeowPsycheTool


@singleton
class MeowPsycheCore:
    SCOPE = "main"
    MEM_TYPE = "llm_fast_response"
    SHORT_PATH = os.path.join(".temp", "public_short_mem.json")

    def __init__(self):
        """心理生成核心：轮询短期记忆，角色每次回复后总结一次当前心理"""
        self.log = DefaultLog().getLogger()
        self.config = MeowPsycheConfig()
        self.tool = MeowPsycheTool()
        self._llm = None
        self._thread = None
        self._stop = Event()
        self._lock = Lock()
        self._last = ""

    def _ensure_llm(self):
        """按平台懒加载心理生成客户端"""
        if self._llm is None:
            if self.config.llm_type == "meowllm":
                from func.psyche.port.meowllm import MeowPsycheMeowLLM
                self._llm = MeowPsycheMeowLLM()
            elif self.config.llm_type == "gemini":
                from func.psyche.port.gemini import MeowPsycheGeminiLLM
                self._llm = MeowPsycheGeminiLLM()
            elif self.config.llm_type == "aliyun":
                from func.psyche.port.aliyun import MeowPsycheAliyunLLM
                self._llm = MeowPsycheAliyunLLM()
            else:
                from func.psyche.port.deepseek import MeowPsycheDeepSeekLLM
                self._llm = MeowPsycheDeepSeekLLM()
        return self._llm

    def _read_short(self):
        """读取短期记忆原始列表"""
        if not os.path.exists(self.SHORT_PATH):
            return []
        try:
            with open(self.SHORT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            self.log.exception("读取短期记忆失败")
            return []

    def _latest_reply(self):
        """当前场景里角色最后一条发言的指纹（用它判断有没有新的一轮，不受短期记忆裁剪影响）"""
        rows = [m for m in self._read_short()
                if isinstance(m, dict) and m.get("role") == "assistant" and m.get("type") == self.MEM_TYPE]
        return str(rows[-1].get("content", ""))[:80] if rows else ""

    def _context(self):
        """取当前场景最近的对话文本作为心理概括输入"""
        rows = [m for m in self._read_short()
                if isinstance(m, dict) and m.get("type") == self.MEM_TYPE
                and m.get("role") in ("user", "assistant") and m.get("content")]
        rounds = max(1, int(self.config.short_rounds or 1))
        rows = rows[-rounds * 2:]
        return "\n".join(f"{'用户' if m['role'] == 'user' else '我'}：{m['content']}" for m in rows)

    def _load_prompt(self):
        """读取心理概括指令文件"""
        path = os.path.join("func", "psyche", "psyche_prompt.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            self.log.exception("读取心理指令失败")
            return ("你是{ai_name}。写下你心里现在装着的。看不出主人在干什么，就留空，一个字都不准编。"
                    "必须调用 note_inner 工具。")

    def ensure_started(self):
        """确保心理轮询线程已启动"""
        if not self.config.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._last = self._latest_reply()
            self._stop.clear()
            self._thread = Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self):
        """轮询短期记忆，发现新的角色发言即触发一次心理总结"""
        while not self._stop.is_set():
            self._stop.wait(self.config.interval_seconds)
            if self._stop.is_set():
                break
            try:
                mark = self._latest_reply()
                if mark and mark != self._last:
                    self._last = mark
                    self.summarize()
            except Exception:
                self.log.exception("心理轮询异常")

    def _parse(self, resp):
        """解析心理工具调用结果"""
        if not resp or not getattr(resp, "choices", None):
            return None
        message = resp.choices[0].message
        for tc in (getattr(message, "tool_calls", None) or []):
            if tc.function.name != MeowPsycheTool.TOOL_NAME:
                continue
            try:
                args = json.loads(tc.function.arguments, strict=False)
            except Exception:
                args = self._parse_loose(tc.function.arguments)
            if isinstance(args, dict):
                return args
        text = str(getattr(message, "content", "") or "").strip()
        if text:
            try:
                args = json.loads(text, strict=False)
            except Exception:
                args = self._parse_loose(text)
            if isinstance(args, dict) and ("theme" in args or "content" in args):
                return args
        return None

    @staticmethod
    def _parse_loose(raw):
        """JSON 坏了就兜底：把话题和内容两个值直接抠出来"""
        text = str(raw or "")
        theme = re.search(r'"theme"\s*:\s*"?([^"\n]*)', text)
        content = re.search(r'"content"\s*:\s*"?([\s\S]*?)"?\s*\}\s*$', text)
        if not theme and not content:
            return None
        value = content.group(1).strip() if content else ""
        if value.count("\n") > 20:
            value = "\n".join(value.split("\n")[:8])
        return {"theme": (theme.group(1).strip() if theme else ""), "content": value}

    @staticmethod
    def _render(data):
        """把心理内容渲染成文本，供续写与排查使用"""
        if not isinstance(data, dict):
            return ""
        theme = str(data.get("theme", "") or "").strip()
        content = [str(c).strip() for c in (data.get("content") or []) if str(c).strip()]
        return "\n".join(([theme] if theme else []) + content)

    def _user_content(self, context):
        """拼装心理内容的输入：话题和内容 + 主人最后这一句 + 最近的对话"""
        from func.pipeline.llm_psyche import LLMPsycheBridge
        parts = ["我心里现在装着的：", self._render(LLMPsycheBridge().get_psyche(self.SCOPE)) or "（还是空的，这是开头）"]
        parts.append(f"最近的对话（最后一条是主人刚说的）：\n{context}")
        return "\n".join(parts)

    def _store(self, data):
        """写入心里的内容：话题和内容都按这一轮写的来"""
        from func.pipeline.llm_psyche import LLMPsycheBridge
        bridge = LLMPsycheBridge()
        theme = str(data.get("theme", "") or "").strip()
        content_raw = data.get("content", [])
        if isinstance(content_raw, str):
            content_raw = content_raw.split("\n")
        content = []
        for line in content_raw or []:
            line = re.sub(r"^\s*(?:[-*·•]|\d+\s*[.、)])\s*", "", str(line)).strip()
            if line:
                content.append(line[:100])
        content = content[:8]
        if not theme:
            # 说不出"在干的事"：清空，别让上一件事的内容挂在心里
            LLMPsycheBridge().set_psyche(self.SCOPE, {})
            return
        bridge.set_psyche(self.SCOPE, {"theme": theme, "content": content})

    def summarize(self):
        """生成一次心理状态并写入桥接，失败返回空串"""
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            return ""
        context = self._context()
        if not context.strip():
            return ""
        system_text = self._load_prompt().replace("{ai_name}", str(AppConfig().ai_name or ""))
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": self._user_content(context)},
        ]
        resp = llm.chat(messages, tools=self.tool.build_tools(), tool_choice=self.tool.force_tool_choice())
        data = self._parse(resp)
        if not data:
            return ""
        self._store(data)
        return data
