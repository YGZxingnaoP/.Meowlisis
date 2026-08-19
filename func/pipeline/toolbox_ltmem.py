# -*- coding: utf-8 -*-
# func/pipeline/toolbox_ltmem.py
# Toolbox 传递长期记忆桥接

from func.log.default_log import DefaultLog
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge


class ToolboxLtMemBridge:
    """Toolbox → 长期记忆传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.ltmem = MeowLLMLtMemBridge()

    def record_toolbox_message(self, username: str, text: str):
        """将 toolbox 输出内容以 AI 消息记录到记忆系统"""
        from func.config.app_config import AppConfig
        self.ltmem.record_ai_message(username, AppConfig().ai_name, text)
