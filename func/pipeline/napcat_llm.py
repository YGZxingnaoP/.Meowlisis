# -*- coding: utf-8 -*-
# func/pipeline/napcat_llm.py
# NapCat → LLM 桥接（独立回复链路）

from typing import List, Optional, Callable

from func.log.default_log import DefaultLog


class NapcatLLMBridge:
    """NapCat → LLM 传递桥接：调用 napcat 独立回复链路"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_llm(self, username: str, user_id: str, text: str, short_memory: List[dict],
                    on_segment: Optional[Callable[[str], None]] = None) -> str:
        """将 QQ 用户消息 + 短期记忆送入 napcat 独立 LLM 链路，返回完整回复。

        on_segment 回调用于流式短句回传（由 toolbox_core 提供，负责发送到 NapCat）。
        """
        from func.toolbox.napcat.llm.napcat_llm import TBNapCatLLM
        self.log.info(f"NapCat → LLM: {username} {text[:30]}...")
        return TBNapCatLLM().reply(username, user_id, text, short_memory, on_segment)
