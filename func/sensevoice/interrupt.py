# -*- coding: utf-8 -*-
# func/sensevoice/interrupt.py
# 说话状态检测

import time
from typing import Optional

import numpy as np


class InterruptDetector:
    """基于能量检测维护说话状态，并返回状态变化事件"""

    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.energy_threshold = config.energy_threshold
        self.silence_threshold = config.silence_threshold
        self.is_speaking = False
        self._silence_start_time = None

    def update(self, data: bytes) -> Optional[str]:
        """处理一帧音频，返回 started/stopped/None 状态变化事件"""
        energy = self._compute_energy(data)
        now = time.time()
        is_speech = energy >= self.energy_threshold
        event = None

        if is_speech:
            # 检测到说话：清除静音计时，若刚从安静切换则上报 started
            self._silence_start_time = None
            if not self.is_speaking:
                self.is_speaking = True
                event = 'started'
        else:
            # 静音期间：累计静音时长，超过阈值则切换为停止说话
            if self.is_speaking:
                if self._silence_start_time is None:
                    self._silence_start_time = now
                elif now - self._silence_start_time >= self.silence_threshold:
                    self.is_speaking = False
                    self._silence_start_time = None
                    event = 'stopped'

        return event

    def _compute_energy(self, data: bytes) -> float:
        """计算音频帧的 RMS 能量"""
        audio_array = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(audio_array ** 2)))
