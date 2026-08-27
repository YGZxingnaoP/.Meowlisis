# -*- coding: utf-8 -*-
# func/pipeline/toolbox_llm.py
# Toolbox 传递 LLM 桥接（统一入口）
#
# - ToolboxLLMBridge：通用 toolbox 工具输出 → 主 LLM 快速回复链
#   （支持弹幕 source / 朗读前置段 / 多用户标记）
# - NapcatLLMBridge：NapCat 私聊独立回复链路
# - NapcatGroupLLMBridge：NapCat 群聊独立回复链路

import uuid
from typing import List, Optional, Callable

from func.log.default_log import DefaultLog


class ToolboxLLMBridge:
    """Toolbox → LLM 传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_llm(self, text: str, username: str, source: str = "toolbox",
                    preamble_text: str = "", traceid: str = "",
                    multi_user: bool = False, memory_config: dict = None):
        """将 toolbox 工具输出内容送入 LLM 快速回复链。

        :param text: 要送入 LLM 的文本（弹幕为「【弹幕】用户名: 内容」包装）
        :param username: 用户名（供长期记忆/用户档案归档）
        :param source: 来源标记（toolbox / danmaku），danmaku 会走弹幕提示词
        :param preamble_text: 朗读前置段（弹幕朗读），由主链路 Output 先送 TTS 再回复
        :param traceid: 复用外部 traceid（弹幕朗读与回复共享同一任务，保证连续）
        :param multi_user: 是否多用户弹幕（后置词用「挑选一些回复」）
        :param memory_config: 弹幕专属记忆配置（仅弹幕传），与其它模块隔离
        """
        from func.llm.llm_core import LLmCore
        traceid = traceid or str(uuid.uuid4())
        self.log.info(f"[{traceid}] Toolbox → LLM: {text[:50]}...")
        LLmCore().msg_deal(
            traceid, text, username,
            source=source, preamble_text=preamble_text, multi_user=multi_user,
            memory_config=memory_config,
        )


class NapcatLLMBridge:
    """NapCat → LLM 传递桥接：调用 napcat 独立回复链路"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_llm(self, username: str, user_id: str, text: str, short_memory: List[dict],
                    on_segment: Optional[Callable[[str], None]] = None,
                    nsfw: bool = False) -> str:
        """将 QQ 用户消息 + 短期记忆送入 napcat 独立 LLM 链路，返回完整回复。

        on_segment 回调用于流式短句回传（由 toolbox_core 提供，负责发送到 NapCat）。
        nsfw=True 时切割减小（不按逗号切）。
        """
        from func.toolbox.napcat.llm.napcat_llm import TBNapCatLLM
        self.log.info(f"NapCat → LLM: {username} {text[:30]}...")
        return TBNapCatLLM().reply(username, user_id, text, short_memory, on_segment, nsfw=nsfw)


class NapcatGroupLLMBridge:
    """NapCat 群聊 → LLM 传递桥接（独立回复链路，群聊专用）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def reply(self, username: Optional[str], group_id: str, group_name: str, text: str,
              short_memory: List[dict], group_info_text: str = "",
              on_segment: Optional[Callable[[str], None]] = None,
              nsfw: bool = False) -> str:
        """@ 触发/强制回复：流式生成，on_segment 回调短句发送到群

        nsfw=True 时切割减小（不按逗号切）。
        """
        from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
        self.log.info(f"NapCat 群聊 → LLM: {group_name} {text[:30]}...")
        return TBNapCatGroupLLM().reply(
            username, group_id, group_name, text, short_memory, group_info_text, on_segment,
            nsfw=nsfw
        )

    def decide(self, username: Optional[str], group_id: str, group_name: str, text: str,
               short_memory: List[dict], group_info_text: str = "",
               ask_bot_tools: Optional[List[dict]] = None) -> str:
        """阈值触发：决策是否插话 / 是否调用 ask_group_bot / 输出 pass"""
        from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
        return TBNapCatGroupLLM().decide(
            username, group_id, group_name, text, short_memory, group_info_text, ask_bot_tools
        )
