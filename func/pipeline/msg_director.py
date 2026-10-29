# -*- coding: utf-8 -*-
# func/pipeline/msg_director.py
# msg / chat / sensevoice → 导演模块桥接：导演激活且允许时接管用户回合

from func.log.default_log import DefaultLog


class MsgDirectorBridge:
    """把主链路用户回合转给 llm_active 的导演表演引擎。

    - 导演已激活、主链路空闲、未被静默/插件/唱歌占用 → 入队并返回 True
      （上层跳过主 LLM 回复）；
    - 其它情况返回 False（上层继续原链路）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_director(self, text, meowid="", source="msg", traceid=""):
        """返回 True 表示本回合已被导演模块接管"""
        if not text or not str(text).strip():
            return False
        try:
            from func.llm_active.director.config import AutoDirectorConfig
            if not AutoDirectorConfig().enabled:
                return False
            from func.pipeline.llm_director import LLMDirectorBridge
            if not LLMDirectorBridge().can_take_over():
                return False
            from func.pipeline.silence_state import SilenceState
            if SilenceState().muted:
                return False
            if not self._plugins_allow():
                return False
            if self._singing():
                return False
            from func.llm_active.director.core import DirectorCore
            if DirectorCore().enqueue_user_turn(meowid, str(text).strip(), source, traceid):
                self.log.info(f"[导演] 接管用户回合（source={source}）：{str(text)[:30]}")
                return True
            return False
        except Exception:
            self.log.exception("msg → 导演模块处理异常")
            return False

    @staticmethod
    def _plugins_allow():
        """插件状态总线：占用主动回复或语音闲聊时让位"""
        try:
            from func.pipeline.plugins_state import (CAP_ACTIVE_REPLY, CAP_VOICE_CHAT,
                                                     PluginsStateBridge)
            bridge = PluginsStateBridge()
            return bridge.allow(CAP_ACTIVE_REPLY) and bridge.allow(CAP_VOICE_CHAT)
        except Exception:
            return True

    @staticmethod
    def _singing():
        """唱歌期间不接管"""
        try:
            from func.pipeline.singing_state import SingingStateBridge
            return bool(SingingStateBridge().is_singing())
        except Exception:
            return False
