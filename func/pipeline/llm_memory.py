# -*- coding: utf-8 -*-
# func/pipeline/llm_memory.py
# LLM 与 Memory 之间的传递桥接

import random
from func.log.default_log import DefaultLog
from func.config.default_config import defaultConfig


class LLMMemoryBridge:
    """LLM ↔ Memory 双向传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = defaultConfig().get_config()

    def should_use_long_term(self, message: str, trigger_keywords: list) -> bool:
        """判断是否需要触发长期记忆"""
        for keyword in trigger_keywords:
            if keyword in message:
                return True
        if len(message) > 15:
            return random.random() < 0.5
        return False
