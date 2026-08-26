# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/hum_detect/hum_detect.py
# 哼唱检测：有效语音累积满 hum_collect_sec 后立即判定（不等段结束），段结束用完整音频触发匹配
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
    """哼唱检测器（单例）：满 hum_collect_sec 立即判定（不等静音段结束），段结束用完整音频触发匹配"""

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
        # 最近一次判定成功的哼唱音频（float32），供 toolbox_audio 落盘匹配
        self._last_hum_audio = None
        # 本段是否已在满 hum_collect_sec 时判定过（无论成败，只判一次）
        self._checked_at_collect = False
        # 本段是否已判定为哼唱（满 7 秒时通过）；段结束据此用完整音频触发匹配
        self._segment_triggered = False

    def feed(self, frame: bytes):
        """喂一帧 16k 单声道 PCM：有效语音累积，满 hum_collect_sec 立即判定，段结束兜底"""
        try:
            arr = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
            if arr.size == 0:
                return
            rms = float(np.sqrt(np.mean(arr ** 2)))

            with self._lock:
                now = time.time()
                # 有效语音：能量 >= SenseVoice VAD 阈值
                if rms >= self.sv_config.energy_threshold:
                    if self._speech_start == 0.0:
                        self._speech_start = now
                    self._last_sound = now
                else:
                    # 静音超过 SenseVoice silence_threshold → 段结束，分析并清空重来
                    if self._speech_start > 0.0 and now - self._last_sound >= self.sv_config.silence_threshold:
                        self._finish_segment()
                        self._speech_start = 0.0
                        self._last_sound = 0.0
                        # 段结束清空缓冲，保证下一段分析的只有当前语音
                        self._buffer.clear()
                        self._buf_samples = 0
                        self._buf_seconds = 0.0
                        self._checked_at_collect = False
                        self._segment_triggered = False

                # 语音段进行中才累积：只保留当前段的音频（有声 + 段内短静音）
                if self._speech_start > 0.0:
                    self._buffer.append(arr)
                    self._buf_samples += arr.size
                    self._buf_seconds = self._buf_samples / SAMPLE_RATE
                    # 满 hum_collect_sec 立即判定（不等静音段结束），只判一次
                    # 通过仅标记本段为哼唱，不立即触发匹配——等段结束用完整音频匹配
                    if (not self._checked_at_collect
                            and self._buf_seconds >= self.config.hum_collect_sec):
                        self._checked_at_collect = True
                        if self._analyze_buffer():
                            self._segment_triggered = True
        except Exception:
            self.log.exception("[HumDetect] 喂帧异常")

    def _finish_segment(self):
        """一段有效语音结束：用完整段音频触发匹配（后续语音已加入），或兜底判定"""
        if self._speech_start == 0.0:
            return
        # 用当前段累积的语音时长判断（不含段尾静音）
        if self._buf_seconds < self.config.hum_collect_sec:
            return
        # 满 7 秒已确认是哼唱 → 直接用完整段触发匹配
        if self._segment_triggered:
            self._trigger_match()
            return
        # 满 7 秒未通过 → 段结束用完整段兜底判定
        if self._analyze_buffer():
            self._trigger_match()

    def _analyze_buffer(self):
        """判定当前累积缓冲是否为哼唱（yin fl1024），返回 bool，不触发匹配"""
        try:
            with self._lock:
                if self._buf_seconds < self.config.hum_collect_sec:
                    return False
                audio = np.concatenate(list(self._buffer))
            if audio.size < int(SAMPLE_RATE * self.config.hum_collect_sec):
                return False
            import librosa
            f0 = librosa.yin(
                audio.astype(np.float32) / 32768.0,
                fmin=80, fmax=800,
                sr=SAMPLE_RATE, frame_length=1024, hop_length=256,
            )
            valid = f0[~np.isnan(f0)]
            if valid.size < 3:
                return False
            ratio = valid.size / float(f0.size)
            midi = 12.0 * np.log2(valid / 440.0) + 69.0
            # 稳定帧占比：相邻帧音高差 < 阈值半音的帧占比
            # （哼唱音符内音高稳定、占比高；说话音高连续乱飘、占比低）
            abs_diff = np.abs(np.diff(midi))
            stable_ratio = float(np.mean(abs_diff < self.config.f0_stable_half_step))
            unique_notes = len(np.unique(np.round(midi).astype(int)))
            return (
                ratio >= self.config.f0_voiced_ratio
                and stable_ratio >= self.config.f0_stable_ratio
                and unique_notes >= self.config.f0_unique_notes
            )
        except Exception:
            self.log.exception("[HumDetect] 完整分析异常")
            return False

    def _trigger_match(self):
        """用当前完整缓冲设置哼唱音频并触发事件序号（供 toolbox_audio 落盘匹配）"""
        with self._lock:
            if self._buf_seconds < self.config.hum_collect_sec:
                return
            audio = np.concatenate(list(self._buffer))
        if audio.size < int(SAMPLE_RATE * self.config.hum_collect_sec):
            return
        self._last_hum_audio = audio
        self._hum_event_seq += 1

    def consume_hum_audio(self):
        """取出最近一次判定成功的哼唱音频（float32 数组）并清除，供落盘匹配"""
        with self._lock:
            audio = self._last_hum_audio
            self._last_hum_audio = None
            return audio

    def get_hum_event_seq(self):
        """返回当前哼唱段完成事件序号（toolbox_audio 据此检测新事件）"""
        with self._lock:
            return self._hum_event_seq
