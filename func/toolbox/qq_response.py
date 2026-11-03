# -*- coding: utf-8 -*-
# func/toolbox/qq_response.py
# QQ 回复编排入口：私聊/群聊/追聊/看图/幻梦/表情 分别落在 napcat/reply/*.py，
# 这里只做组合与对外入口（receive_qq / receive_group / reply_group_at）。

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.pipeline.short_memory import ShortMemory
from func.pipeline.toolbox_ltmem import NapcatLtMemBridge
from func.pipeline.toolbox_llm import NapcatLLMBridge, NapcatGroupLLMBridge
from func.toolbox.napcat.config import TBNapCatConfig
from func.toolbox.napcat.napcat_core import TBNapCatCore
from func.toolbox.napcat.reply.private import PrivateReplyMixin
from func.toolbox.napcat.reply.group import GroupReplyMixin
from func.toolbox.napcat.reply.followup import FollowupReplyMixin
from func.toolbox.napcat.reply.vision import VisionReplyMixin
from func.toolbox.napcat.reply.bot import BotReplyMixin
from func.toolbox.napcat.reply.emote import EmoteReplyMixin


@singleton
class TBoxQQResponse(PrivateReplyMixin, GroupReplyMixin, FollowupReplyMixin,
                    VisionReplyMixin, BotReplyMixin, EmoteReplyMixin):
    """QQ 回复编排：由各职责 mixin 组合，对外仍是同一组入口

    由 TBoxCore 提供转发入口（receive_qq / receive_group / reply_group_at）调用；
    具体链路的实现分别在 func/toolbox/napcat/reply/ 下。
    """
    # 幻梦被动触发概率（硬编码）：群聊 decide 时，只要幻梦在该群发过言，
    # 就有该概率直接随机调它（替代 LLM 的「冷场」判断，冷场与累计消息矛盾）。
    BOT_TRIGGER_PROB = 0.5

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.napcat_config = TBNapCatConfig()
        self.napcat_core = TBNapCatCore()
        self.napcat_llm = NapcatLLMBridge()
        self.napcat_group_llm = NapcatGroupLLMBridge()
        self.napcat_ltmem = NapcatLtMemBridge()
        self.short_memory = ShortMemory()
