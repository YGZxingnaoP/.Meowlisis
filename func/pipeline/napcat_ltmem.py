# -*- coding: utf-8 -*-
# func/pipeline/napcat_ltmem.py
# NapCat → 长期记忆桥接

from func.log.default_log import DefaultLog
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
from func.toolbox.napcat.config import TBNapCatConfig


class NapcatLtMemBridge:
    """NapCat → 长期记忆传递桥接（默认关闭，内容加【来自QQ的消息】前缀）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.ltmem = MeowLLMLtMemBridge()
        self.config = TBNapCatConfig()

    def record_user(self, username: str, text: str):
        """记录 QQ 用户消息到长期记忆（受 ltmem_enabled 开关控制）"""
        if not self.config.ltmem_enabled:
            return
        self.ltmem.record_user_message(username, f"【来自QQ的消息】{text}")

    def record_ai(self, username: str, text: str):
        """记录 AI 回复到长期记忆（受 ltmem_enabled 开关控制）"""
        if not self.config.ltmem_enabled:
            return
        from func.config.app_config import AppConfig
        self.ltmem.record_ai_message(username, AppConfig().ai_name, f"【来自QQ的消息】{text}")
