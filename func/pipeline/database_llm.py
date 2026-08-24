# -*- coding: utf-8 -*-
# func/pipeline/database_llm.py
# database song_review → LLM 桥接：把感想引导词交给 LLM 合成并播报，记录记忆
from func.log.default_log import DefaultLog
from func.pipeline.system_prompt import SystemPromptBridge
from func.pipeline.toolbox_tts import ToolboxTtsBridge
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
from func.pipeline.short_memory import ShortMemory
from func.config.app_config import AppConfig


class DatabaseLLMBridge:
    """song_review 感想合成：不带用户信息与用户档案，max_tokens 可配置"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_guide(self, guide_msg):
        """把感想引导词交给 LLM 生成感想，播报并记录记忆"""
        if not guide_msg or not guide_msg.strip():
            return ""
        try:
            from func.meowsinger.port import get_singer_llm
            llm = get_singer_llm()
            if llm is None or not llm.client:
                self.log.error("[DatabaseLLM] meowsinger LLM 不可用")
                return ""
            system_prompt = SystemPromptBridge().get_persona_prompt()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": guide_msg.strip()},
            ]
            resp = llm.chat(messages, max_tokens=self._sentiment_max_tokens())
            content = ""
            if resp and getattr(resp, "choices", None):
                content = (resp.choices[0].message.content or "").strip()
            if not content:
                return ""
            ToolboxTtsBridge().send_stream(content, source="meowsinger_sentiment")
            self._record_memory(content)
            self._trigger_summary()
            return content
        except Exception:
            self.log.exception("[DatabaseLLM] 感想合成异常")
            return ""

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
    def _record_memory(content):
        """感想面向大家：只记长期记忆与摘要，不记用户记忆"""
        try:
            ShortMemory().save({"role": "assistant", "content": content, "type": "llm_fast_response"},
                               40, trim_mode="rounds")
        except Exception:
            pass
        try:
            MeowLLMLtMemBridge().record_ltmem_only(AppConfig().ai_name, content)
        except Exception:
            pass
