# -*- coding: utf-8 -*-
# func/llm_active/director/judge.py
# 无聊判官：每轮主链路回复结束后异步判断「主人是不是没意思了 / 话题是不是断了」

import os
import json
import threading

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.llm_active.director.config import AutoDirectorConfig
from func.llm_active.director.tools import JUDGE_TOOL_NAME, judge_tool
from func.pipeline.llm_psyche import LLMPsycheBridge
from func.pipeline.short_memory import ShortMemory


class DirectorJudge:
    """判官：纯 LLM 判断，不用任何关键词；判 true 必须引用原话"""

    def __init__(self, core):
        self.log = DefaultLog().getLogger()
        self.core = core
        self._lock = threading.Lock()
        self._running = False
        self._last = ""

    # ==================== 入口（主链路回复完成时） ====================
    def on_ai_reply(self, source="llm"):
        """LLMTimerBridge 订阅回调（在回复线程里，只做轻量判断后转后台线程）"""
        if source == "danmaku":
            return
        cfg = AutoDirectorConfig()
        if not cfg.enabled or not cfg.judge_enabled:
            return
        if self.core.is_active():
            return
        if not self.core.cooldown_ok():
            return
        if self._silenced_or_paused():
            return
        rows = self._recent_rows()
        fingerprint = self._fingerprint(rows)
        if not fingerprint:
            return
        with self._lock:
            if self._running or fingerprint == self._last:
                return
            self._last = fingerprint
            self._running = True
        threading.Thread(target=self._run, args=(rows,), daemon=True).start()

    # ==================== 判断 ====================
    def _run(self, rows):
        try:
            if self.core.is_active() or not self.core.cooldown_ok():
                return
            messages = [
                {"role": "system", "content": self._system()},
                {"role": "user", "content": self._user(rows)},
            ]
            resp = self.core.judge_llm.chat(
                messages, tools=[judge_tool()],
                tool_choice={"type": "function", "function": {"name": JUDGE_TOOL_NAME}},
                options={"enable_thinking": False},
            )
            args = self._parse(resp)
            if not args:
                return
            reason = str(args.get("reason") or "").strip()
            bored = bool(args.get("bored")) or bool(args.get("no_topic"))
            if not bored or not reason:
                return
            self.log.info(f"[导演] 判官命中：{reason[:60]}")
            if self.core.is_active():
                return
            try:
                from func.pipeline.llm_director import LLMDirectorBridge
                if LLMDirectorBridge().host_busy():
                    self.log.info("[导演] 主链路正在回复，本次不抢着开口")
                    return
            except Exception:
                pass
            next_hint = str(args.get("next") or "").strip()
            trigger_reason = reason + (f"｜我想{next_hint}" if next_hint else "")
            from func.llm_active.active_core import AutoActiveCore
            if AutoActiveCore().trigger_now(trigger_reason):
                self.core.set_cooldown()
                self.log.info("[导演] 已跳过计时，立即触发一次主动回复")
        except Exception:
            self.log.exception("[导演] 判官执行异常")
        finally:
            with self._lock:
                self._running = False

    # ==================== 提示词 ====================
    def _system(self) -> str:
        ai_name = str(AppConfig().ai_name or "")
        instruction = self._load_prompt().replace("{ai_name}", ai_name)
        psyche = self._psyche_text()
        if psyche:
            return f"{instruction}\n\n【我现在的心理】\n{psyche}"
        return instruction

    @staticmethod
    def _user(rows) -> str:
        lines = []
        for m in rows:
            who = "主人" if m.get("role") == "user" else "我"
            lines.append(f"{who}：{m.get('content', '')}")
        body = "\n".join(lines) if lines else "（还没有对话）"
        return (f"【最近几轮】\n{body}\n\n"
                f"只判断主人现在是不是没意思了、话题是不是断了。必须调用 {JUDGE_TOOL_NAME}。")

    @staticmethod
    def _psyche_text() -> str:
        try:
            data = LLMPsycheBridge().get_psyche("main") or {}
            theme = str(data.get("theme", "") or "").strip()
            content = [str(c).strip() for c in (data.get("content") or []) if str(c).strip()]
            return "\n".join(([theme] if theme else []) + content)
        except Exception:
            return ""

    # ==================== 输入/解析 ====================
    def _recent_rows(self):
        try:
            rounds = max(1, int(AutoDirectorConfig().judge_history_rounds))
            return ShortMemory().load_by_type(("llm_fast_response",))[-rounds * 2:]
        except Exception:
            self.log.exception("[导演] 判官读取短期记忆失败")
            return []

    @staticmethod
    def _fingerprint(rows) -> str:
        for m in reversed(rows or []):
            if m.get("role") == "assistant":
                return str(m.get("content") or "")[:80]
        return ""

    @staticmethod
    def _parse(resp):
        if not resp or not getattr(resp, "choices", None):
            return None
        msg = resp.choices[0].message
        for tc in (getattr(msg, "tool_calls", None) or []):
            if str(getattr(tc.function, "name", "")) != JUDGE_TOOL_NAME:
                continue
            try:
                args = json.loads(tc.function.arguments or "{}", strict=False)
            except Exception:
                return None
            return args if isinstance(args, dict) else None
        return None

    @staticmethod
    def _silenced_or_paused() -> bool:
        try:
            from func.pipeline.silence_state import SilenceState
            if SilenceState().muted:
                return True
        except Exception:
            pass
        try:
            from func.pipeline.singing_state import SingingStateBridge
            if SingingStateBridge().is_singing():
                return True
        except Exception:
            pass
        try:
            from func.pipeline.plugins_state import (CAP_ACTIVE_REPLY, CAP_VOICE_CHAT,
                                                     PluginsStateBridge)
            bridge = PluginsStateBridge()
            return not (bridge.allow(CAP_ACTIVE_REPLY) and bridge.allow(CAP_VOICE_CHAT))
        except Exception:
            return False

    @staticmethod
    def _load_prompt() -> str:
        path = os.path.join("func", "llm_active", "director", "prompts", "judge_prompt.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ("你是{ai_name}。判断主人现在是不是没意思了、话题是不是断了。"
                    "必须调用 judge_bored，reason 必须引用原话。")
