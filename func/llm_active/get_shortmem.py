# -*- coding: utf-8 -*-
# func/llm_active/get_shortmem.py
# 主动回复短期记忆获取

from func.pipeline.short_memory import ShortMemory


class AutoGetShortMem:
    """从 pipeline 短期记忆桥接获取完整短期记忆"""

    def __init__(self):
        self.short_memory = ShortMemory()

    def load(self):
        """加载全部短期记忆（role/content 格式）"""
        return self.short_memory.load()
