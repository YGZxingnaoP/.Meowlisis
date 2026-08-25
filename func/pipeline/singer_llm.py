# -*- coding: utf-8 -*-
# func/pipeline/singer_llm.py
# meowsinger → LLM 桥接：把内部回复信息以角色身份合成并播报，记录记忆
from func.log.default_log import DefaultLog
from func.pipeline.system_prompt import SystemPromptBridge
from func.pipeline.toolbox_tts import ToolboxTtsBridge
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
from func.pipeline.short_memory import ShortMemory
from func.config.app_config import AppConfig


class SingerLLMBridge:
    """meowsinger 内部回复合成：带 user 与完整 system_prompt，以角色身份回答"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_reply(self, internal_text, username=""):
        """把内部信息（如"不会唱这首歌"）生成角色口吻回复，播报并记录记忆"""
        if not internal_text or not internal_text.strip():
            return ""
        username = username or "主人"
        try:
            from func.meowsinger.port import get_singer_llm
            llm = get_singer_llm()
            if llm is None or not llm.client:
                self.log.error("[SingerLLM] meowsinger LLM 不可用")
                return ""
            system_prompt = SystemPromptBridge().get_system_prompt(username, internal_text)
            from func.meowsinger.config import MeowSingerConfig
            template = MeowSingerConfig().prompt_reply
            if not template:
                return ""
            guide = template.replace("{content}", internal_text.strip())
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": guide},
            ]
            resp = llm.chat(messages)
            content = ""
            if resp and getattr(resp, "choices", None):
                content = (resp.choices[0].message.content or "").strip()
            if not content:
                return ""
            from func.llm.output import clean_and_split
            cleaned_content, segments = clean_and_split(content)
            if not segments:
                return ""
            import uuid as _uuid
            traceid = str(_uuid.uuid4())
            for i, seg in enumerate(segments):
                chat_status = "end" if i == len(segments) - 1 else ""
                ToolboxTtsBridge().send_to_answer_queue(
                    seg, traceid=traceid, seg_index=i,
                    chat_status=chat_status, source="meowsinger",
                )
            self._record_memory(username, cleaned_content)
            return content
        except Exception:
            self.log.exception("[SingerLLM] 回复合成异常")
            return ""

    def send_summary(self, lines):
        """把唱歌期间汇总的观众消息交给 LLM 统一回复，播报并记录记忆"""
        if not lines or not lines.strip():
            return ""
        try:
            from func.meowsinger.port import get_singer_llm
            llm = get_singer_llm()
            if llm is None or not llm.client:
                self.log.error("[SingerLLM] meowsinger LLM 不可用")
                return ""
            system_prompt = SystemPromptBridge().get_system_prompt("主人", lines)
            from func.meowsinger.config import MeowSingerConfig
            template = MeowSingerConfig().prompt_summary
            if not template:
                return ""
            guide = template.replace("{lines}", lines)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": guide},
            ]
            resp = llm.chat(messages)
            content = ""
            if resp and getattr(resp, "choices", None):
                content = (resp.choices[0].message.content or "").strip()
            if not content:
                return ""
            from func.llm.output import clean_and_split
            cleaned_content, segments = clean_and_split(content)
            if not segments:
                return ""
            import uuid as _uuid
            traceid = str(_uuid.uuid4())
            for i, seg in enumerate(segments):
                chat_status = "end" if i == len(segments) - 1 else ""
                ToolboxTtsBridge().send_to_answer_queue(
                    seg, traceid=traceid, seg_index=i,
                    chat_status=chat_status, source="meowsinger_summary",
                )
            self._record_ai_public(cleaned_content)
            return content
        except Exception:
            self.log.exception("[SingerLLM] 汇总回复合成异常")
            return ""

    @staticmethod
    def _record_memory(username, content):
        try:
            ShortMemory().save({"role": "assistant", "content": content, "type": "llm_fast_response"},
                               40, trim_mode="rounds")
        except Exception:
            pass
        try:
            MeowLLMLtMemBridge().record_ai_message(username, AppConfig().ai_name, content)
        except Exception:
            pass

    @staticmethod
    def _record_ai_public(content):
        """AI 面向大家的回复：只记长期记忆与摘要，不记用户记忆"""
        try:
            ShortMemory().save({"role": "assistant", "content": content, "type": "llm_fast_response"},
                               40, trim_mode="rounds")
        except Exception:
            pass
        try:
            MeowLLMLtMemBridge().record_ltmem_only(AppConfig().ai_name, content)
        except Exception:
            pass
