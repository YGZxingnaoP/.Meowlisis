# -*- coding: utf-8 -*-
# func/vts/emotion_mapper.py
# 情绪槽位解析：emotion + intensity → VTS hotkeyID

from func.vts.config import VtsConfig


class VtsEmotionMapper:
    """根据情绪与强度解析出 VTS hotkeyID（逻辑委托 VtsConfig.resolve_hotkey）"""

    def __init__(self):
        self.config = VtsConfig()

    def resolve(self, emotion: str, intensity: float) -> str:
        """返回解析出的 hotkeyID；为空表示未配置/无需发送"""
        return self.config.resolve_hotkey(emotion, intensity)
