# -*- coding: utf-8 -*-
# func/catpaws/memory.py
# 记忆桥接：操作中的用户指导与角色回复同时写短期记忆、长期记忆、记忆摘要
from func.catpaws.config import CWCatPawsConfig
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

CW_MEM_USER = "phone_control_user"
CW_MEM_REPLY = "phone_control_response"


@singleton
class CWCatPawsMemory:
    """catpaws 记忆写入（短期 + 长期 + 摘要 + 用户记忆）"""

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        self.config = config or CWCatPawsConfig()

    def user(self, meowid, text):
        """记录用户在手机链路里说的话"""
        body = str(text or "").strip()
        if not body:
            return
        self._short("user", body, CW_MEM_USER)
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            MeowLLMLtMemBridge().record_user_message(meowid, body)
        except Exception:
            self.log.exception("[CatPaws] 写用户长期记忆失败")

    def reply(self, meowid, text):
        """记录角色在手机链路里说的话（type=phone_control_response）"""
        body = str(text or "").strip()
        if not body:
            return
        self._short("assistant", body, CW_MEM_REPLY)
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            MeowLLMLtMemBridge().record_ai_message(meowid, self._ai_name(), body)
        except Exception:
            self.log.exception("[CatPaws] 写角色长期记忆失败")

    def _short(self, role, content, mem_type):
        try:
            from func.pipeline.short_memory import ShortMemory
            rounds = int(self.config.short_rounds or 0)
            ShortMemory().save({"role": role, "content": content, "type": mem_type},
                               rounds, trim_mode="rounds")
        except Exception:
            self.log.exception("[CatPaws] 写短期记忆失败")

    @staticmethod
    def _ai_name():
        try:
            from func.config.app_config import AppConfig
            return AppConfig().ai_name or "AI"
        except Exception:
            return "AI"
