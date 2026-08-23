# -*- coding: utf-8 -*-
# func/llm_active/get_prompt.py
# 主动回复系统提示词获取

from func.pipeline.system_prompt import SystemPromptBridge


class AutoGetPrompt:
    """从 system_prompt 桥接获取主动回复专用系统提示词（不含用户档案）"""

    def __init__(self):
        self.bridge = SystemPromptBridge()

    def get_active_prompt(self, cold_time, current_message: str = "",
                          topic_override: str = "") -> str:
        """获取主动回复系统提示词：前置词追加空闲提示 + 角色主体（含空闲占位）"""
        return self.bridge.get_active_prompt(cold_time, current_message, topic_override)
