# -*- coding: utf-8 -*-
# func/pipeline/singing_state.py
# 唱歌状态桥接：对外查询唱歌状态 + 唱歌开始/结束副作用（暂停/恢复主动回复计时）
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class SingingStateBridge:
    """唱歌状态对外桥接（单例）：统一状态与副作用，业务模块只通过本桥接读写"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def is_singing(self):
        """查询是否正在唱歌"""
        try:
            from func.meowsinger.state import MeowSingerState
            return MeowSingerState().is_singing()
        except Exception:
            self.log.exception("[SingingState] 查询唱歌状态异常")
            return False

    def start_singing(self, mode, song_title=""):
        """唱歌开始：更新状态 + 暂停主动回复计时"""
        try:
            from func.meowsinger.state import MeowSingerState
            MeowSingerState().start_singing(mode, song_title)
        except Exception:
            self.log.exception("[SingingState] 更新唱歌状态异常")
        self._pause_active()

    def end_singing(self):
        """唱歌结束：更新状态 + 恢复主动回复计时"""
        try:
            from func.meowsinger.state import MeowSingerState
            MeowSingerState().end_singing()
        except Exception:
            self.log.exception("[SingingState] 结束唱歌状态异常")
        self._resume_active()

    @staticmethod
    def _pause_active():
        try:
            from func.llm_active.active_core import AutoActiveCore
            AutoActiveCore().pause()
        except Exception:
            pass

    @staticmethod
    def _resume_active():
        try:
            from func.llm_active.active_core import AutoActiveCore
            AutoActiveCore().resume()
        except Exception:
            pass
