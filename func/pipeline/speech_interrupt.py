# -*- coding: utf-8 -*-
# func/pipeline/speech_interrupt.py
# 用户开口/新消息的打断代际：各条生成链路（主链路 / 导演）都按它收手
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class SpeechInterruptBridge:
    """打断信号的唯一入口：取代际、判定是否被打断、主动打断"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def token(self) -> int:
        """生成开始前记下代际"""
        from func.llm.state import LLmState
        return LLmState().abort_token()

    def aborted(self, token: int) -> bool:
        """这一轮是否已被打断"""
        from func.llm.state import LLmState
        return LLmState().aborted(token)

    def bump(self, reason: str = "用户开口") -> int:
        """打断当前生成（不写记忆、不播报）"""
        from func.llm.state import LLmState
        epoch = LLmState().bump_abort()
        self.log.info(f"[打断] {reason}，当前生成收手（epoch={epoch}）")
        return epoch
