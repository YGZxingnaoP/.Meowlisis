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



from func.pipeline.id_signup import display_name
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
        if self.config.local_llm_type == "meowllm":
            from func.llm.port.meowllm import MeowLLMLLM
            return MeowLLMLLM(self.config)
        if self.config.local_llm_type == "gemini":
            from func.llm.port.gemini import GeminiLLM
            return GeminiLLM(self.config)
        if self.config.local_llm_type == "aliyun":
            return AliyunLLM(self.config)
        return DeepSeekLLM(self.config)

    def remind(self, uid, time_str, content):
        base = SystemPromptBridge().get_system_prompt(uid, "", mark_first=False)
        prompt = (
            f"{base}\n\n"
            f"【你此刻想到的事】现在是{time_str}，你想起了要提醒{display_name(uid)}：{content}\n"
            f"这是你主动开口说话，第一句就是你要说给{display_name(uid)}听的话；不要复述提醒内容，"
            f"不要出现“好的”“收到”“我这就”这类回应指令的话。"
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"提醒事项：{content}"},
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
            self.ltmem.record_ai_message(uid, AppConfig().ai_name, final_text)
        self.log.info(f"[{traceid}][待办提醒]{uid}: {final_text}")
        return final_text
