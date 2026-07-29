# -*- coding: utf-8 -*-
# func/pipeline/memory_llm.py
# Memory 与 LLM 的互相传递桥接

from func.log.default_log import DefaultLog


class MemoryLLMBridge:
    """Memory ↔ LLM 互相传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def add_user_message(self, memory, message: str, username: str):
        """将用户消息写入记忆"""
        memory.add_user_message(message, username)

    def add_assistant_message(self, memory, message: str):
        """将助手回复写入记忆"""
        memory.add_assistant_message(message)

    def build_messages(self, memory, prompt: str, username: str, include_long_term: bool = True):
        """从记忆构建消息列表"""
        return memory.build_messages(prompt, username=username, include_long_term=include_long_term)
