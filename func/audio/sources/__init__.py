# -*- coding: utf-8 -*-
# func/audio/sources/__init__.py
# 音频输入源统一导出

from func.audio.sources.base import BaseAudioSource
from func.audio.sources.microphone import MicrophoneSource
from func.audio.sources.loopback import LoopbackSource
from func.audio.sources.inject import InjectSource

__all__ = ["BaseAudioSource", "MicrophoneSource", "LoopbackSource", "InjectSource"]
