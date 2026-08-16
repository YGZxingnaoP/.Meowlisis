# -*- coding: utf-8 -*-
# func/pipeline/system_prompt.py
# 系统提示词传递桥接（输入端为 catbrain 模块）

from func.log.default_log import DefaultLog


class SystemPromptBridge:
    """系统提示词桥接（输入端为 catbrain，尚未实现，先保留占位）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        # catbrain 未实现，暂存空提示词
        self._prompt = ""

    def get_system_prompt(self) -> str:
        """获取完整系统提示词"""
        return self._prompt

    def set_system_prompt(self, prompt: str):
        """设置系统提示词（供 catbrain 未来调用）"""
        self._prompt = prompt
