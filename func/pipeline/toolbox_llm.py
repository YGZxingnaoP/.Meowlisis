# -*- coding: utf-8 -*-
# func/pipeline/toolbox_llm.py
# Toolbox 传递 LLM 桥接

import uuid

from func.log.default_log import DefaultLog


class ToolboxLLMBridge:
    """Toolbox → LLM 传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_llm(self, text: str, username: str):
        """将 toolbox 工具输出内容送入 LLM 快速回复链"""
        from func.llm.llm_core import LLmCore
        traceid = str(uuid.uuid4())
        self.log.info(f"[{traceid}] Toolbox → LLM: {text[:50]}...")
        LLmCore().msg_deal(traceid, text, username)
