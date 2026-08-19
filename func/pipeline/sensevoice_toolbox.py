# -*- coding: utf-8 -*-
# func/pipeline/sensevoice_toolbox.py
# SenseVoice 传递 toolbox 桥接

from func.log.default_log import DefaultLog


class SenseVoiceToolboxBridge:
    """SenseVoice → Toolbox 传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_toolbox(self, text: str, username: str):
        """将 SenseVoice 识别文本送入 toolbox 处理链"""
        from func.toolbox.toolbox_core import TBoxCore
        self.log.info(f"SenseVoice → Toolbox: {text[:50]}...")
        TBoxCore().receive(text, username)
