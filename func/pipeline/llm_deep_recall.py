# -*- coding: utf-8 -*-
# func/pipeline/llm_deep_recall.py
# 主链深度回忆桥接：快速回复后判官 → 摘要优先取数 → 工具补读 → 同一 traceid 续说

import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.pipeline.deep_recall_core import (
    chat_complete, judge, load_options, run as run_recall,
)
from func.pipeline.deep_recall_narration import DeepRecallNarration
from func.pipeline.short_memory import ShortMemory
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge


@singleton
class LLMDeepRecallBridge:
    """只做编排与输出，不直接改主链编排队列"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._birthday_seen = set()

    def enabled(self) -> bool:
        try:
            return bool(load_options("llm").get("enabled"))
        except Exception:
            return False

    # ==================== 入口（Output.finalize 调用） ====================
    def after_reply(self, output, traceid: str, quick_text: str, source: str = "llm"):
        opts = load_options("llm")
        if not opts.get("enabled"):
            output.close(traceid)
            return
        if str(source or "") == "danmaku":
            output.close(traceid)
            return
        uid = ""
        user_text = ""
        try:
            uid = str(MeowLLMLtMemBridge().last_uid or "")
            for item in reversed(ShortMemory().load_by_type(("llm_fast_response", "other_talks"))):
                if item.get("role") == "user" and item.get("content"):
                    user_text = str(item.get("content") or "")
                    break
        except Exception:
            self.log.exception("[深度回忆] 读取当前用户失败")
        if not uid or not user_text:
            output.close(traceid)
            return
        stop_event = threading.Event()
        timer = threading.Timer(
            max(5.0, float(opts.get("timeout_s") or 20) + 5.0),
            lambda: self._force_close(output, traceid, stop_event))
        timer.daemon = True
        timer.start()
        threading.Thread(
            target=self._run,
            args=(output, traceid, uid, user_text, str(quick_text or ""), source,
                  opts, stop_event, timer),
            daemon=True, name="deep-recall-main").start()

    @staticmethod
    def _force_close(output, traceid, stop_event=None):
        """看门狗：判官/生成卡死时也要把 TTS 任务收掉"""
        if stop_event is not None:
            stop_event.set()
        try:
            output.close(traceid)
        except Exception:
            pass

    # ==================== 内部 ====================
    def _run(self, output, traceid, uid, user_text, quick_text, source, opts,
             stop_event=None, timer=None):
        stop_event = stop_event or threading.Event()
        try:
            from func.pipeline.speech_interrupt import SpeechInterruptBridge
            abort = SpeechInterruptBridge()
            token = abort.token()

            def chat_fn(messages, tools=None, tool_choice=None, max_tokens=512):
                from func.llm.llm_core import LLmCore
                return chat_complete(LLmCore().llm, messages, tools, tool_choice, max_tokens)

            birthday = False
            try:
                from func.calendar.birthday import DateBirthday
                birthday = bool(DateBirthday().is_today(uid))
            except Exception:
                birthday = False
            if birthday:
                key = f"{uid}:{__import__('datetime').date.today()}"
                if key in self._birthday_seen:
                    birthday = False
                else:
                    self._birthday_seen.add(key)
            verdict = judge(chat_fn, uid, user_text, quick_text, birthday=birthday, opts=opts)
            if not verdict.get("need"):
                output.close(traceid)
                return
            if abort.aborted(token) or stop_event.is_set():
                output.close(traceid)
                return
            persona = ""
            try:
                from func.pipeline.system_prompt import SystemPromptBridge
                persona = SystemPromptBridge().get_persona_prompt() or ""
            except Exception:
                persona = ""
            options = dict(opts)
            if verdict.get("kind") == "birthday":
                options["max_extra_chars"] = max(120, int(opts.get("max_extra_chars") or 180))
            text = run_recall(
                chat_fn, uid, user_text, quick_text, options, persona=persona,
                emit=(lambda body: self._emit(output, traceid, body, abort, token)),
                query=str(verdict.get("query") or user_text),
                stop=(lambda: abort.aborted(token) or stop_event.is_set()),
                birthday=birthday)
            if text and not abort.aborted(token) and not stop_event.is_set():
                self._remember(uid, text)
                self.log.info(f"[深度回忆] 主链补充 {len(text)} 字：{text[:60]}")
            output.close(traceid)
        except Exception:
            self.log.exception("[深度回忆] 主链执行异常")
            try:
                output.close(traceid)
            except Exception:
                pass
        finally:
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    pass

    @staticmethod
    def _emit(output, traceid, text, abort, token):
        if abort.aborted(token):
            return
        try:
            text = DeepRecallNarration().clean(text)
        except Exception:
            pass
        if not str(text or "").strip():
            return
        output.send_extension(text, traceid)

    def _remember(self, uid: str, text: str):
        """补说作为新的 assistant 追加，写入深度回忆独立 narration 处理后的文本"""
        try:
            text = DeepRecallNarration().clean(text)
        except Exception:
            pass
        if not str(text or "").strip():
            return
        try:
            from func.config.app_config import AppConfig
            from func.llm.llm_core import LLmCore
            builder = LLmCore().message_builder
            builder.add_assistant_message(uid, text, AppConfig().ai_name)
        except Exception:
            self.log.exception("[深度回忆] 写短期记忆失败")
        try:
            from func.config.app_config import AppConfig
            MeowLLMLtMemBridge().record_ai_message(uid, AppConfig().ai_name, text)
        except Exception:
            self.log.exception("[深度回忆] 写长期记忆失败")
