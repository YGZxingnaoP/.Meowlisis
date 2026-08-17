# -*- coding: utf-8 -*-
# func/llm/prompt_get.py
# 从 pipeline 获取系统提示词

from func.pipeline.system_prompt import SystemPromptBridge


class PromptGet:
    """从 pipeline 的 system_prompt 桥接获取完整系统提示词"""

    def __init__(self):
        self.bridge = SystemPromptBridge()

    def get_system_prompt(self, username=None, current_message: str = "") -> str:
        """获取完整系统提示词（来源为 catbrain，传入当前消息供记忆摘要检索）"""
        return self.bridge.get_system_prompt(username, current_message)
