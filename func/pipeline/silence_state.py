# -*- coding: utf-8 -*-
# func/pipeline/silence_state.py
# 全局静默状态：仅由语音关键短句触发，静默期间拦截所有 AI 出声

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class SilenceState:
    """静默状态单例：维护 muted 开关，并联动暂停/恢复主动回复。

    - 进入静默：语音命中 mute_phrases（不要说话等）；
    - 退出静默：语音命中 wake_phrases（喵呜等）；
    - 判断全部为子串匹配，不依赖 LLM；
    - 词表每次检测时读最新配置，支持前端保存后热更新。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.muted = False

    def _cfg(self) -> dict:
        """读取 silence 节点最新配置（热更新）"""
        import yaml
        try:
            with open('config.yml', 'r', encoding='utf-8') as f:
                root = yaml.safe_load(f) or {}
            return root.get('silence', {}) or {}
        except Exception:
            self.log.exception("读取 silence 配置失败")
            return {}

    @property
    def enabled(self) -> bool:
        return bool(self._cfg().get('enabled', True))

    def hit_wake(self, text: str) -> bool:
        """文本是否命中唤醒词"""
        if not text:
            return False
        cfg = self._cfg()
        if not cfg.get('enabled', True):
            return False
        phrases = [str(w) for w in (cfg.get('wake_phrases') or [])]
        return any(w and w in text for w in phrases)

    def hit_mute(self, text: str) -> bool:
        """文本是否命中静默词"""
        if not text:
            return False
        cfg = self._cfg()
        if not cfg.get('enabled', True):
            return False
        phrases = [str(w) for w in (cfg.get('mute_phrases') or [])]
        return any(w and w in text for w in phrases)

    def mute(self):
        """进入静默（幂等）"""
        if self.muted:
            return
        self.muted = True
        self.log.info("🔇 进入静默状态（关键短句触发）")
        self._pause_active()

    def unmute(self):
        """退出静默（幂等）"""
        if not self.muted:
            return
        self.muted = False
        self.log.info("🔊 解除静默状态（唤醒词触发）")
        self._resume_active()

    @staticmethod
    def _pause_active():
        """静默时暂停主动回复计时"""
        try:
            from func.llm_active.active_core import AutoActiveCore
            AutoActiveCore().pause()
        except Exception:
            pass

    @staticmethod
    def _resume_active():
        """恢复主动回复计时"""
        try:
            from func.llm_active.active_core import AutoActiveCore
            AutoActiveCore().resume()
        except Exception:
            pass
