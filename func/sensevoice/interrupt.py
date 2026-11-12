# -*- coding: utf-8 -*-
# func/sensevoice/interrupt.py
# 说话状态检测 + 打断检测（两者使用不同能量阈值）

import time
from collections import deque
from typing import Optional

import numpy as np


class InterruptDetector:
    """基于能量检测维护「说话状态」与「打断状态」，分别使用不同阈值。

    - 说话状态（VAD）：energy >= energy_threshold，用于上报服务端说话状态；
    - 打断状态：最近 INTERRUPT_HOLD_SECONDS 的平均能量 >= interrupt_threshold 才成立
      （按窗口平均值而非连续单帧判定，字与字之间的低能量帧不会重置计时）。
    """

    # 打断判定窗口（秒）：窗口内平均能量达标才置位
    INTERRUPT_HOLD_SECONDS = 0.9

    def __init__(self, config):
        self.energy_threshold = config.energy_threshold
        # 起句仍用高阈值防噪声；句内保活用更低的阈值，
        # 否则一句话中途音量掉到 650 以下就被当成静音，1.3 秒后截成 0.5 秒碎片，
        # 声纹（CAM++）在碎片上必然匹配失败，表现为“语音没反应”。
        self.keep_threshold = max(250.0, float(self.energy_threshold) * 0.7)
        self.interrupt_threshold = getattr(config, 'interrupt_threshold', config.energy_threshold)
        self.silence_threshold = config.silence_threshold
        # 说话状态（VAD）
        self.is_speaking = False
        # 打断状态
        self.is_interrupting = False
        self._silence_start_time = None
        self._interrupt_silence_start = None
        self._interrupt_window = deque()   # (now, energy)：最近窗口内的能量采样
        self._interrupt_window_start = None

    def update_vad(self, data: bytes) -> Optional[str]:
        """仅更新说话状态（VAD），返回 vad_event"""
        energy = self._compute_energy(data)
        now = time.time()
        return self._update_speaking(energy, now)

    def update_interrupt(self, data: bytes) -> Optional[str]:
        """仅更新打断状态，返回 interrupt_event"""
        energy = self._compute_energy(data)
        now = time.time()
        return self._update_interrupt(energy, now)

    def _update_speaking(self, energy: float, now: float) -> Optional[str]:
        """说话状态（VAD）：起句用高阈值，句内保活用低阈值（迟滞）"""
        threshold = self.keep_threshold if self.is_speaking else self.energy_threshold
        is_speech = energy >= threshold
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
        """打断状态：窗口平均能量达标才置位（停止仍按单帧判定，独立于 VAD 阈值）"""
        avg = self._interrupt_window_avg(energy, now)
        event = None
        if self.is_interrupting:
            if energy >= self.interrupt_threshold:
                self._interrupt_silence_start = None
            elif self._interrupt_silence_start is None:
                self._interrupt_silence_start = now
            elif now - self._interrupt_silence_start >= self.silence_threshold:
                self.is_interrupting = False
                self._interrupt_silence_start = None
                event = 'stopped'
        elif avg is not None and avg >= self.interrupt_threshold:
            self.is_interrupting = True
            event = 'started'
        return event

    def _interrupt_window_avg(self, energy: float, now: float) -> Optional[float]:
        """压入本帧能量并返回最近窗口的平均值（窗口未铺满则返回 None）"""
        self._interrupt_window.append((now, energy))
        horizon = now - self.INTERRUPT_HOLD_SECONDS
        while self._interrupt_window[0][0] <= horizon:
            self._interrupt_window.popleft()
        if self._interrupt_window_start is None:
            self._interrupt_window_start = now
        if now - self._interrupt_window_start < self.INTERRUPT_HOLD_SECONDS:
            return None
        return sum(e for _, e in self._interrupt_window) / len(self._interrupt_window)

    def reset_speaking(self):
        """强制复位说话状态（按住说话松手后调用，保证下一句能重新触发 started）"""
        self.is_speaking = False
        self._silence_start_time = None

    def _compute_energy(self, data: bytes) -> float:
        """计算音频帧的 RMS 能量"""
        audio_array = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if audio_array.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(audio_array ** 2)))
