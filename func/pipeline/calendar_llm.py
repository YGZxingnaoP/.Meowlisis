# -*- coding: utf-8 -*-
# func/pipeline/calendar_llm.py
# 待办提醒 → LLM 语音桥接：直接调用主 LLM 生成提醒语并送 TTS

import uuid

from func.log.default_log import DefaultLog
from func.llm.config import LLMConfig
from func.llm.state import LLmState
from func.llm.output import Output
from func.llm.port.deepseek import DeepSeekLLM
from func.llm.port.aliyun import AliyunLLM
from func.pipeline.short_memory import ShortMemory
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
from func.pipeline.system_prompt import SystemPromptBridge
from func.config.app_config import AppConfig


class DateCalendarLLM:
    """待办提醒语音链路：构建提示词 → 流式 LLM → TTS → 写记忆"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = LLMConfig()
        self.llm_data = LLmState()
        self.short_memory = ShortMemory()
        self.ltmem = MeowLLMLtMemBridge()
        self.llm = self._create_llm()

    def _create_llm(self):
        if self.config.local_llm_type == "aliyun":
            return AliyunLLM(self.config)
        return DeepSeekLLM(self.config)

    def remind(self, username, time_str, content):
        prompt = SystemPromptBridge().get_system_prompt(username, "", mark_first=False)
        guide = f"现在是{time_str}，你必须提醒{username}，{content}"
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": guide},
        ]
        traceid = str(uuid.uuid4())
        output = Output(self.config, self.llm_data)
        stream = self.llm.chat_stream(messages)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                output.process_chunk(delta.content, traceid)
        final_text = output.finalize(traceid)
        if final_text:
            self.short_memory.save(
                {"role": "assistant", "content": final_text, "type": "llm_active_response"},
                self.config.short_term_rounds,
            )
            self.ltmem.record_ai_message(username, AppConfig().ai_name, final_text)
        self.log.info(f"[{traceid}][待办提醒]{username}: {final_text}")
        return final_text
