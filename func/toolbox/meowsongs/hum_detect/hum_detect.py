# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/hum_detect/hum_detect.py
# 哼唱检测：有效语音累积满 hum_collect_sec 后一次性完整分析（音高+旋律+时长）
import time
import threading
from collections import deque

import numpy as np

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.meowsongs.config import TBMeowSongsConfig
from func.sensevoice.config import SenseVoiceConfig

SAMPLE_RATE = 16000


@singleton
class TBHumDetect:
    """哼唱检测器（单例）：与 SenseVoice 相同的有效语音累积逻辑，攒够时长一次性判断"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBMeowSongsConfig()
        self.sv_config = SenseVoiceConfig()
        self._lock = threading.RLock()
        self._buffer = deque()
        self._buf_samples = 0
        self._buf_seconds = 0.0
        # 有效语音累积状态（与 SenseVoice 一致）
        self._speech_start = 0.0
        self._last_sound = 0.0
        # 哼唱段完成事件序号（每判定成功一段 +1，供 toolbox_audio 检测）
        self._hum_event_seq = 0

    def feed(self, frame: bytes):
        """喂一帧 16k 单声道 PCM：有效语音累积，段结束一次性分析"""
        try:
            arr = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
            if arr.size == 0:
                return
            rms = float(np.sqrt(np.mean(arr ** 2)))

            with self._lock:
                self._buffer.append(arr)
                self._buf_samples += arr.size
                self._buf_seconds = self._buf_samples / SAMPLE_RATE
                while self._buf_seconds > self.config.cache_seconds:
                    old = self._buffer.popleft()
                    self._buf_samples -= old.size
                    self._buf_seconds = self._buf_samples / SAMPLE_RATE

                now = time.time()
                # 有效语音：能量 >= SenseVoice VAD 阈值
                if rms >= self.sv_config.energy_threshold:
                    if self._speech_start == 0.0:
                        self._speech_start = now
                    self._last_sound = now
                else:
                    # 静音超过 SenseVoice silence_threshold → 段结束，分析并清空重来
                    if self._speech_start > 0.0 and now - self._last_sound >= self.sv_config.silence_threshold:
                        self._finish_segment(now)
                        self._speech_start = 0.0
                        self._last_sound = 0.0
        except Exception:
            self.log.exception("[HumDetect] 喂帧异常")

    def _finish_segment(self, now):
        """一段有效语音结束：攒够 hum_collect_sec 且音高旋律通过才产生哼唱事件"""
        if self._speech_start == 0.0:
            return
        duration = now - self._speech_start
        if duration < self.config.hum_collect_sec:
            # 不足 7 秒：只走 ASR，不算哼唱
            return
        if self._analyze_buffer():
            self._hum_event_seq += 1

    def _analyze_buffer(self):
        """对累积缓冲做完整音高+旋律分析，返回是否判为哼唱"""
        try:
            with self._lock:
                if self._buf_seconds < self.config.hum_collect_sec:
                    return False
                audio = np.concatenate(list(self._buffer))
            if audio.size < int(SAMPLE_RATE * self.config.hum_collect_sec):
                return False
            import librosa
            f0, voiced, _ = librosa.pyin(
                audio.astype(np.float32) / 32768.0,
                fmin=80, fmax=800,
                sr=SAMPLE_RATE, frame_length=1024,
            )
            valid = f0[voiced]
            if valid.size == 0:
                return False
            ratio = valid.size / float(f0.size)
            midi = 12.0 * np.log2(valid / 440.0) + 69.0
            var = float(np.var(midi))
            unique_notes = len(np.unique(np.round(midi).astype(int)))
            return (
                ratio >= self.config.f0_voiced_ratio
                and var <= self.config.f0_stability
                and unique_notes >= self.config.f0_unique_notes
            )
        except Exception:
            self.log.exception("[HumDetect] 完整分析异常")
            return False

    def get_hum_event_seq(self):
        """返回当前哼唱段完成事件序号（toolbox_audio 据此检测新事件）"""
        with self._lock:
            return self._hum_event_seq
