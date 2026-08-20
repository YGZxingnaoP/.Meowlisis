# -*- coding: utf-8 -*-
# func/sensevoice/interrupt.py
# 说话状态检测 + 打断检测（两者使用不同能量阈值）

import time
from typing import Optional, Tuple

import numpy as np


class InterruptDetector:
    """基于能量检测维护「说话状态」与「打断状态」，分别使用不同阈值。

    - 说话状态（VAD）：energy >= energy_threshold，用于上报服务端说话状态；
    - 打断状态：energy >= interrupt_threshold，用于触发 TTS 打断（更严格）。
    """

    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.energy_threshold = config.energy_threshold
        self.interrupt_threshold = getattr(config, 'interrupt_threshold', config.energy_threshold)
        self.silence_threshold = config.silence_threshold
        # 说话状态（VAD）
        self.is_speaking = False
        # 打断状态
        self.is_interrupting = False
        self._silence_start_time = None
        self._interrupt_silence_start = None

    def update(self, data: bytes) -> Tuple[Optional[str], Optional[str]]:
        """处理一帧音频，返回 (vad_event, interrupt_event)。

        事件取值：'started' / 'stopped' / None
        """
        energy = self._compute_energy(data)
        now = time.time()
        vad_event = self._update_speaking(energy, now)
        interrupt_event = self._update_interrupt(energy, now)
        return vad_event, interrupt_event

    def _update_speaking(self, energy: float, now: float) -> Optional[str]:
        """说话状态（VAD）：energy >= energy_threshold"""
        is_speech = energy >= self.energy_threshold
        event = None
        if is_speech:
            self._silence_start_time = None
            if not self.is_speaking:
                self.is_speaking = True
                event = 'started'
        else:
            if self.is_speaking:
                if self._silence_start_time is None:
                    self._silence_start_time = now
                elif now - self._silence_start_time >= self.silence_threshold:
                    self.is_speaking = False
                    self._silence_start_time = None
                    event = 'stopped'
        return event

    def _update_interrupt(self, energy: float, now: float) -> Optional[str]:
        """打断状态：energy >= interrupt_threshold（独立于 VAD 阈值）"""
        is_interrupt_speech = energy >= self.interrupt_threshold
        event = None
        if is_interrupt_speech:
            self._interrupt_silence_start = None
            if not self.is_interrupting:
                self.is_interrupting = True
                event = 'started'
        else:
            if self.is_interrupting:
                if self._interrupt_silence_start is None:
                    self._interrupt_silence_start = now
                elif now - self._interrupt_silence_start >= self.silence_threshold:
                    self.is_interrupting = False
                    self._interrupt_silence_start = None
                    event = 'stopped'
        return event

    def _compute_energy(self, data: bytes) -> float:
        """计算音频帧的 RMS 能量"""
        audio_array = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if audio_array.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio_array ** 2)))
