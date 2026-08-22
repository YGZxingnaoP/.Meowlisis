# -*- coding: utf-8 -*-
# func/pipeline/toolbox_ltmem.py
# Toolbox 传递长期记忆桥接（统一入口）
#
# - ToolboxLtMemBridge：通用 toolbox 输出以 AI 消息记录到记忆系统
# - NapcatLtMemBridge：NapCat → 长期记忆与用户档案传递桥接

from func.log.default_log import DefaultLog
from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
from func.toolbox.napcat.config import TBNapCatConfig


class ToolboxLtMemBridge:
    """Toolbox → 长期记忆传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.ltmem = MeowLLMLtMemBridge()

    def record_toolbox_message(self, username: str, text: str):
        """将 toolbox 输出内容以 AI 消息记录到记忆系统"""
        from func.config.app_config import AppConfig
        self.ltmem.record_ai_message(username, AppConfig().ai_name, text)


class NapcatLtMemBridge:
    """NapCat → 长期记忆与用户档案传递桥接

    - 用户档案记录（新用户建档 / 按轮数更新）始终执行，不跟随 ltmem_enabled 开关；
    - 长期记忆存储与摘要缓存受 ltmem_enabled 开关控制；
    - 内容统一加【来自QQ的消息】前缀。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.ltmem = MeowLLMLtMemBridge()
        self.config = TBNapCatConfig()

    def record_user(self, username: str, text: str):
        """记录 QQ 用户消息：用户档案始终记录；长期记忆受开关控制"""
        if not username:
            return
        msg = f"【来自QQ的消息】{text}"
        # 1. 用户档案记录：始终执行（不跟随长期记忆开关）
        try:
            self.ltmem.record_user_profile(username, msg)
        except Exception:
            self.log.exception("NapCat 记录用户档案失败")
        # 2. 长期记忆 + 摘要缓存：受开关控制
        if self.config.ltmem_enabled:
            self.ltmem.record_ltmem_only(username, msg)

    def record_ai(self, username: str, text: str):
        """记录 AI 回复到长期记忆（受 ltmem_enabled 开关控制）"""
        if not self.config.ltmem_enabled:
            return
        from func.config.app_config import AppConfig
        self.ltmem.record_ai_message(username, AppConfig().ai_name, f"【来自QQ的消息】{text}")
