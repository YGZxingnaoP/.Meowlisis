# -*- coding: utf-8 -*-
# func/toolbox/get_prompt.py
# 从 pipeline 获取系统提示词

from func.pipeline.system_prompt import SystemPromptBridge


class TBoxGetPrompt:
    """从 pipeline 的 system_prompt 桥接获取完整系统提示词"""

    def __init__(self):
        self.bridge = SystemPromptBridge()

    def get_system_prompt(self, username=None, current_message: str = "") -> str:
        """获取完整系统提示词（对话型：含用户记忆/日期/摘要/说话对象，供对话场景使用）"""
        return self.bridge.get_system_prompt(username, current_message)

    def get_tool_prompt(self, username=None, current_message: str = "") -> str:
        """获取决策/工具用提示词（角色人设：前置词+角色卡+价值观+后置词，无用户记忆、无说话对象）"""
        return self.bridge.get_tool_prompt(username, current_message)
