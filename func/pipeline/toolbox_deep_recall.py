# -*- coding: utf-8 -*-
# func/pipeline/toolbox_deep_recall.py
# QQ 深度回忆桥接：快速短句后判官 → 摘要优先取数 → 工具补读 → 追加 1~2 条

import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.pipeline.deep_recall_core import (
    chat_complete, judge, load_options, run as run_recall,
)
from func.toolbox.napcat.config import TBNapCatConfig


@singleton
class ToolboxDeepRecallBridge:
    """QQ 侧深度回忆：不直接操作 LLM 编排，只经 toolbox 端口与 pipeline 取数"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._birthday_seen = set()

    def enabled(self) -> bool:
        try:
            return bool(load_options("qq").get("enabled"))
        except Exception:
            return False

    # ==================== 入口 ====================
    def after_reply(self, uid: str, text: str, quick_text: str, send,
                    channel: str = "private", group_name: str = "",
                    serious: bool = False, memory_type: str = "qq_response",
                    memory_limit: int = 0):
        opts = load_options("qq")
        if not opts.get("enabled"):
            return
        if not uid or not str(text or "").strip() or not str(quick_text or "").strip():
            return
        threading.Thread(
            target=self._run,
            args=(uid, str(text or ""), str(quick_text or ""), send,
                  channel, group_name, bool(serious), opts,
                  memory_type, int(memory_limit or 0)),
            daemon=True, name="deep-recall-qq").start()

    # ==================== 内部 ====================
    def _run(self, uid, user_text, quick_text, send, channel, group_name, serious, opts,
             memory_type, memory_limit):
        stop_event = threading.Event()
        timer = threading.Timer(
            max(5.0, float(opts.get("timeout_s") or 20) + 5.0), stop_event.set)
        timer.daemon = True
        timer.start()
        try:
            from func.pipeline.speech_interrupt import SpeechInterruptBridge
            abort = SpeechInterruptBridge()
            token = abort.token()
            from func.toolbox.napcat.analysis.analysis_core import TBNapcatAnalysis
            port = TBNapcatAnalysis._llm()

            def chat_fn(messages, tools=None, tool_choice=None, max_tokens=512):
                return chat_complete(port, messages, tools, tool_choice, max_tokens)

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
            verdict = judge(chat_fn, uid, user_text, quick_text,
                            birthday=birthday, opts=opts)
            if not verdict.get("need"):
                return
            persona = ""
            try:
                from func.pipeline.system_prompt import SystemPromptBridge
                persona = SystemPromptBridge().get_persona_prompt() or ""
            except Exception:
                persona = ""
            extra = run_recall(
                chat_fn, uid, user_text, quick_text, opts, persona=persona,
                query=str(verdict.get("query") or user_text),
                stop=stop_event.is_set, birthday=birthday)
            extra = str(extra or "").strip()
            if not extra or stop_event.is_set() or abort.aborted(token):
                return
            try:
                from func.toolbox.napcat.llm.narration import QQNarration
                extra = QQNarration().clean(extra)
            except Exception:
                pass
            chunks = self._chunks(extra, channel, serious,
                                  int(opts.get("max_messages") or 2),
                                  int(opts.get("max_extra_chars") or 100))
            sent = 0
            for chunk in chunks:
                if stop_event.is_set() or abort.aborted(token):
                    return
                try:
                    send(chunk)
                    sent += 1
                except Exception:
                    self.log.exception("[深度回忆] QQ 追加发送失败")
            if sent:
                self._remember(uid, extra, memory_type, memory_limit)
                self.log.info(f"[深度回忆] QQ 追加 {sent} 条：{extra[:60]}")
        except Exception:
            self.log.exception("[深度回忆] QQ 执行异常")
        finally:
            try:
                timer.cancel()
            except Exception:
                pass

    def _remember(self, uid: str, text: str, memory_type: str, memory_limit: int):
        """补发内容也写回短期/长期记忆，避免下一轮角色不记得自己刚说过"""
        cfg = TBNapCatConfig()
        try:
            if memory_type and cfg.short_mem_enabled:
                from func.pipeline.short_memory import ShortMemory
                ShortMemory().save(
                    {"role": "assistant", "content": text, "type": memory_type},
                    memory_limit or cfg.short_mem_rounds)
        except Exception:
            self.log.exception("[深度回忆] QQ 写短期记忆失败")
        try:
            if cfg.ltmem_enabled:
                from func.pipeline.toolbox_ltmem import NapcatLtMemBridge
                NapcatLtMemBridge().record_ai(uid, text)
        except Exception:
            self.log.exception("[深度回忆] QQ 写长期记忆失败")

    @staticmethod
    def _cut(text: str, limit: int) -> str:
        text = str(text or "").strip()
        if len(text) <= limit:
            return text
        head = text[:limit]
        for mark in ("。", "！", "？", "!", "?", "\n"):
            pos = head.rfind(mark)
            if pos >= max(0, limit // 2):
                return head[:pos + 1].strip()
        for mark in ("，", ",", "；", ";"):
            pos = head.rfind(mark)
            if pos >= max(0, limit // 2):
                return head[:pos].strip()
        return head.strip()

    @staticmethod
    def _chunks(text: str, channel: str, serious: bool, max_messages: int,
                max_chars: int = 100):
        """按单条补说上限切成 1~2 条；优先在句号/换行处截断"""
        from func.toolbox.napcat.llm.napcat_llm import TBNapCatLLM
        from func.toolbox.napcat.llm.format_guard import clean_serious, strip_markdown
        cfg = TBNapCatConfig()
        if serious:
            conf = cfg.serious_conf(channel)
            limit = int(int(conf.get("word_count") or 100) * float(conf.get("ratio") or 1.5))
            limit = min(limit, int(max_chars or 100))
            text = clean_serious(text, limit)
        else:
            limit = int(max_chars or 100)
            text = strip_markdown(TBNapCatLLM.remove_analysis(text))
        limit = max(12, limit)
        segs = TBNapCatLLM.split_segments(text, serious=bool(serious)) or [text]
        raw = []
        buf = ""
        for seg in segs:
            seg = str(seg or "").strip()
            if not seg:
                continue
            cand = f"{buf}。{seg}" if buf else seg
            if buf and len(cand) > limit:
                raw.append(buf)
                buf = seg
            else:
                buf = cand
        if buf:
            raw.append(buf)
        max_messages = max(1, int(max_messages))
        if len(raw) <= max_messages:
            return [ToolboxDeepRecallBridge._cut(c, limit) for c in raw if c.strip()]
        head = raw[:max_messages - 1]
        tail = "。".join(raw[max_messages - 1:])
        tail = ToolboxDeepRecallBridge._cut(tail, limit)
        if tail:
            head.append(tail)
        return [ToolboxDeepRecallBridge._cut(c, limit) for c in head if c.strip()]
