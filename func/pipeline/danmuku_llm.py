# -*- coding: utf-8 -*-
# func/pipeline/danmuku_llm.py
# 弹幕传递 LLM 桥接

import uuid

from func.log.default_log import DefaultLog
from func.llm.llm_core import LLmCore


class DanmukuLLMBridge:
    """弹幕 → LLM 传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_llm(self, text: str, uid: str, username: str):
        """将弹幕文本送入 LLM 处理链"""
        traceid = str(uuid.uuid4())
        self.log.info(f"[{traceid}] 弹幕 → LLM: {text[:50]}...")
        LLmCore().msg_deal(traceid, text, uid, username)
