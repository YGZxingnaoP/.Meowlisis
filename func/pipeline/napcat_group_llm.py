# -*- coding: utf-8 -*-
# func/pipeline/napcat_group_llm.py
# NapCat 群聊 → LLM 桥接（独立回复链路，群聊专用）

from typing import List, Optional, Callable

from func.log.default_log import DefaultLog


class NapcatGroupLLMBridge:
    """NapCat 群聊 → LLM 传递桥接：调用群聊独立回复链路"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def reply(self, username: Optional[str], group_id: str, group_name: str, text: str,
              short_memory: List[dict], group_info_text: str = "",
              on_segment: Optional[Callable[[str], None]] = None) -> str:
        """@ 触发/强制回复：流式生成，on_segment 回调短句发送到群"""
        from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
        self.log.info(f"NapCat 群聊 → LLM: {group_name} {text[:30]}...")
        return TBNapCatGroupLLM().reply(
            username, group_id, group_name, text, short_memory, group_info_text, on_segment
        )

    def decide(self, username: Optional[str], group_id: str, group_name: str, text: str,
               short_memory: List[dict], group_info_text: str = "",
               ask_bot_tools: Optional[List[dict]] = None) -> str:
        """阈值触发：决策是否插话 / 是否调用 ask_group_bot / 输出 pass"""
        from func.toolbox.napcat.llm.napcat_group_llm import TBNapCatGroupLLM
        return TBNapCatGroupLLM().decide(
            username, group_id, group_name, text, short_memory, group_info_text, ask_bot_tools
        )
