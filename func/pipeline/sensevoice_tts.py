# -*- coding: utf-8 -*-
# func/pipeline/sensevoice_tts.py
# SenseVoice 与 TTS 之间的说话状态传递桥接
from func.tools.singleton_mode import singleton


@singleton
class SenseVoiceTtsBridge:
    """共享说话状态，供 TTS 做打断决策"""

    def __init__(self):
        self._speaking = False

    def set_speaking(self, speaking: bool):
        """写入当前说话状态"""
        self._speaking = speaking

    def is_speaking(self) -> bool:
        """读取当前说话状态"""
        return self._speaking
