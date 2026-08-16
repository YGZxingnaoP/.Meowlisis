# -*- coding: utf-8 -*-
# func/sensevoice/audio.py
# 音频数据采集与处理

class AudioProcessor:
    """负责分帧尺寸计算、静音帧生成与帧数据整理"""

    def __init__(self, config, log, microphone):
        self.config = config
        self.log = log
        self.microphone = microphone
        self.chunk = config.chunk
        self.frame_duration = config.chunk_size_ms / 1000.0

    def create_silence_frame(self) -> bytes:
        """生成一帧全零静音数据"""
        return b'\x00' * (self.chunk * 2)

    def next_frame(self) -> bytes:
        """获取下一帧音频，麦克风关闭或无数据时返回静音帧"""
        if self.microphone.is_enabled():
            frame = self.microphone.read()
            if frame is not None:
                return frame
        return self.create_silence_frame()
