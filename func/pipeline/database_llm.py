# -*- coding: utf-8 -*-
# func/pipeline/database_llm.py
# database song_review → LLM 桥接：把感想引导词交给 LLM 合成并播报，记录记忆
from func.log.default_log import DefaultLog
from func.pipeline.system_prompt import SystemPromptBridge
from func.pipeline.toolbox_tts import ToolboxTtsBridge
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
from func.pipeline.short_memory import ShortMemory
from func.config.app_config import AppConfig
from func.meowsinger.narration import SingerNarration


class DatabaseLLMBridge:
    """song_review 感想合成：不带用户信息与用户档案，max_tokens 可配置"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._uid = ""
        self._song_title = ""
        self._mode = "song"

    def generate(self, guide_msg, song_title="", mode="song", uid=""):
        """只生成感想文本（不播报），返回 (cleaned_content, segments)，失败返回 (None, None)"""
        if not guide_msg or not guide_msg.strip():
            return None, None
        self._uid = str(uid or "").strip()
        self._song_title = str(song_title or "").strip()
        self._mode = str(mode or "song")
        try:
            from func.meowsinger.port import get_singer_llm
            llm = get_singer_llm()
            if llm is None or not llm.client:
                self.log.error("[DatabaseLLM] meowsinger LLM 不可用")
                return None, None
            system_prompt = SystemPromptBridge().get_persona_prompt()
            hint = ""
            title = str(song_title or "").strip()
            if title:
                verb = "翻唱" if str(mode or "") == "cover" else "播放"
                hint = f"【唱歌提示】刚刚{verb}了《{title}》。这是点歌/唱歌后的感想，不要当成普通聊天。\n\n"
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": hint + guide_msg.strip()},
            ]
            resp = llm.chat(messages, max_tokens=self._sentiment_max_tokens())
            content = ""
            if resp and getattr(resp, "choices", None):
                content = (resp.choices[0].message.content or "").strip()
            if not content:
                return None, None
            try:
                content = SingerNarration().clean(content)
            except Exception:
                pass
            from func.llm.output import clean_and_split
            cleaned_content, segments = clean_and_split(content)
            if not segments:
                return None, None
            return cleaned_content, segments
        except Exception:
            self.log.exception("[DatabaseLLM] 感想生成异常")
            return None, None

    def broadcast(self, cleaned_content, segments, song_title="", mode="song", uid=""):
        """播报已生成的感想：TTS 播报 + 短期/长期/摘要/用户记忆"""
        if not segments:
            return ""
        try:
            import uuid as _uuid
            traceid = str(_uuid.uuid4())
            for i, seg in enumerate(segments):
                chat_status = "end" if i == len(segments) - 1 else ""
                ToolboxTtsBridge().send_to_answer_queue(
                    seg, traceid=traceid, seg_index=i,
                    chat_status=chat_status, source="meowsinger_sentiment",
                )
            self._record_memory(
                cleaned_content,
                uid or self._uid,
                song_title or self._song_title,
                mode or self._mode,
            )
            self._trigger_summary()
            return cleaned_content
        except Exception:
            self.log.exception("[DatabaseLLM] 感想播报异常")
            return ""

    def send_guide(self, guide_msg, song_title="", mode="song", uid=""):
        """兼容入口：生成 + 播报（供需要一步到位的场景）"""
        cleaned_content, segments = self.generate(
            guide_msg, song_title=song_title, mode=mode, uid=uid)
        if not segments:
            return ""
        return self.broadcast(
            cleaned_content, segments, song_title=song_title, mode=mode, uid=uid)

    @staticmethod
    def _sentiment_max_tokens():
        try:
            from func.pipeline.config_reader import ConfigReader
            cfg = ConfigReader().get('meowsinger', {})
            sentiment = cfg.get('sentiment', {}) if isinstance(cfg, dict) else {}
            return int(sentiment.get('max_tokens', 2048) or 2048)
        except Exception:
            return 2048

    @staticmethod
    def _trigger_summary():
        try:
            from func.pipeline.msg_singer import MsgSingerBridge
            MsgSingerBridge().trigger_summary()
        except Exception:
            pass

    @staticmethod
    def _memory_tag(song_title, mode):
        title = str(song_title or "").strip()
        if str(mode or "") == "cover":
            return f"刚刚唱了《{title}》" if title else "刚刚唱了"
        return f"刚刚听了《{title}》" if title else "刚刚听了"

    def _record_memory(self, content, uid="", song_title="", mode="song"):
        """写短期 + 长期 + 摘要缓存 + 用户记忆；标注点歌/唱歌"""
        text = f"{self._memory_tag(song_title, mode)}{content}"
        uid = str(uid or "").strip()
        if uid:
            try:
                from func.pipeline.id_signup import IdSignupBridge
                if not IdSignupBridge.is_internal_uid(uid):
                    self.log.warning(f"[DatabaseLLM] 非标准 meowid，忽略用户记忆：{uid!r}")
                    uid = ""
            except Exception:
                self.log.exception("[DatabaseLLM] meowid 校验异常")
        try:
            ShortMemory().save({"role": "assistant", "content": text, "type": "singer_thought"},
                               0, trim_mode="rounds")
        except Exception:
            pass
        try:
            bridge = MeowLLMLtMemBridge()
            if uid:
                bridge.record_ai_message(uid, AppConfig().ai_name, text)
            else:
                self.log.warning("[DatabaseLLM] 感想缺少 meowid，仅写长期记忆与摘要")
                bridge.record_ltmem_only(AppConfig().ai_name, text)
        except Exception:
            self.log.exception("[DatabaseLLM] 写长期/用户记忆失败")
