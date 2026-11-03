# -*- coding: utf-8 -*-
# func/pipeline/sensevoice_llm.py
# SenseVoice 传递 LLM 桥接

import uuid

from func.log.default_log import DefaultLog


class SenseVoiceLLMBridge:
    """SenseVoice → LLM 传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_llm(self, text: str, uid: str, source: str = "llm"):
        """将 SenseVoice 识别文本送入 LLM 处理链

        :param source: 来源标记；inject(手机语音) 由会话传 phone，使回复推手机；
                       本地 mic 默认 llm，回复本地播放
        """
        from func.llm.llm_core import LLmCore
        traceid = str(uuid.uuid4())
        self.log.info(f"[{traceid}] SenseVoice → LLM(source={source}): {text[:50]}...")
        LLmCore().msg_deal(traceid, text, uid, source=source)

    def abort_current(self, reason: str = "用户开口"):
        """用户开口：正在生成的回答立刻收手，不等它想完"""
        try:
            from func.pipeline.speech_interrupt import SpeechInterruptBridge
            SpeechInterruptBridge().bump(reason)
        except Exception:
            self.log.exception("打断当前生成失败")
