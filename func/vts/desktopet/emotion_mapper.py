# -*- coding: utf-8 -*-
# func/vts/desktopet/emotion_mapper.py
# 情绪槽位解析：emotion + intensity → 桌宠 hotkeyID

from func.vts.desktopet.config import DesktopetConfig


class DesktopetEmotionMapper:
    """根据情绪与强度解析出桌宠 hotkeyID（逻辑委托 DesktopetConfig.resolve_hotkey）"""

    def __init__(self):
        self.config = DesktopetConfig()

    def resolve(self, emotion: str, intensity: float) -> str:
        """返回解析出的 hotkeyID；为空表示未配置/无需发送"""
        return self.config.resolve_hotkey(emotion, intensity)
