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

    def record_toolbox_message(self, uid: str, text: str):
        """将 toolbox 输出内容以 AI 消息记录到记忆系统"""
        from func.config.app_config import AppConfig
        self.ltmem.record_ai_message(uid, AppConfig().ai_name, text)


class NapcatLtMemBridge:
    """NapCat → 长期记忆与用户档案传递桥接

    - 用户档案记录（新用户建档 / 按轮数更新）始终执行，不跟随 ltmem_enabled 开关；
    - 长期记忆存储与摘要缓存受 ltmem_enabled 开关控制；
    - 内容统一加前缀：私聊【来自QQ，{昵称}的消息】，群聊【来自QQ，{群名}的群消息】。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.ltmem = MeowLLMLtMemBridge()
        self.config = TBNapCatConfig()

    @staticmethod
    def _mem_prefix(uid: str, name: str = "", group_name: str = "") -> str:
        """长期记忆前缀：群聊用群名；私聊先用 meowid 对应的昵称，没有再回退真实昵称"""
        group_name = str(group_name or "").strip()
        if group_name:
            return f"【来自QQ，{group_name}的群消息】"
        try:
            from func.pipeline.id_signup import IdSignupBridge
            nickname = IdSignupBridge().nickname_of(uid)
        except Exception:
            nickname = ""
        return f"【来自QQ，{str(nickname or name or '').strip()}的消息】"

    def record_user(self, uid: str, text: str, name: str = "", group_name: str = ""):
        """记录 QQ 用户消息：用户档案始终记录；长期记忆受开关控制

        :param name: QQ 真实昵称（外部显示名），meowid 查不到昵称时作为回退
        :param group_name: 群名；群聊消息传它，前缀换成「群消息」
        """
        if not uid:
            return
        msg = f"{self._mem_prefix(uid, name, group_name)}{text}"
        # 1. 用户档案记录：始终执行（不跟随长期记忆开关）
        try:
            self.ltmem.record_user_profile(uid, msg)
        except Exception:
            self.log.exception("NapCat 记录用户档案失败")
        # 2. 长期记忆 + 摘要缓存：受开关控制
        if self.config.ltmem_enabled:
            self.ltmem.record_ltmem_only(uid, msg)

    def record_ai(self, uid: str, text: str, name: str = ""):
        """记录 AI 回复到长期记忆（受 ltmem_enabled 开关控制）

        :param name: QQ 真实昵称（外部显示名），meowid 查不到昵称时作为回退
        """
        if not self.config.ltmem_enabled:
            return
        from func.config.app_config import AppConfig
        self.ltmem.record_ai_message(uid, AppConfig().ai_name,
                                     f"{self._mem_prefix(uid, name)}{text}")
