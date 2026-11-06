# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/hum_detect/hum_detect.py
# 哼唱检测：有效语音累积满 hum_collect_sec 后立即判定并定歌（lock 事件），段结束触发接唱（sing 事件）
# 每个音频源（mic / loopback / inject）各持一份独立状态，互不干扰
import time
import threading
from collections import deque

import numpy as np

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.meowsongs.config import TBMeowSongsConfig
from func.sensevoice.config import SenseVoiceConfig

SAMPLE_RATE = 16000
# 判定用音高范围：覆盖人声哼唱（男声低音 C2 ≈ 65Hz）
F0_MIN = 65.0
F0_MAX = 800.0
# 判定用帧长与帧移：只统计有声/稳定/音符数，不需要更细的时间分辨率
JUDGE_FRAME_LENGTH = 1024
JUDGE_HOP = 1024

DEFAULT_SOURCE = "mic"


class _SourceState:
    """单个音频源的检测状态（缓冲、分段计时、判定结果、事件序号）"""

    __slots__ = (
        "buffer", "buf_samples", "buf_seconds", "speech_start", "last_sound",
        "hum_event_seq", "last_hum_audio", "checked_at_collect", "segment_triggered",
        "last_hum_duration", "last_event_type", "need_discard", "last_metrics",
        "last_segment_hum",
    )

    def __init__(self):
        self.buffer = deque()
        self.buf_samples = 0
        self.buf_seconds = 0.0
        # 有效语音累积状态（与 SenseVoice 一致）
        self.speech_start = 0.0
        self.last_sound = 0.0
        # 哼唱段完成事件序号（每触发一次 +1，供 toolbox_audio 检测）
        self.hum_event_seq = 0
        # 最近一次判定/触发携带的音频（float32），供 toolbox_audio 落盘匹配
        self.last_hum_audio = None
        # 本段是否已在满 hum_collect_sec 时判定过（无论成败，只判一次）
        self.checked_at_collect = False
        # 本段是否已判定为哼唱；段结束据此触发匹配
        self.segment_triggered = False
        # 最近一段哼唱的时长（秒），供接唱定位 offset+时长
        self.last_hum_duration = 0.0
        # 最近一次触发的事件类型："lock"=定歌, "sing"=段结束接唱
        self.last_event_type = ""
        # 判定成功时置位，供 toolbox_audio 落盘时决定是否丢弃对应的 ASR final（只丢一次）
        self.need_discard = False
        # 最近一次判定的指标快照（ratio / stable_ratio / unique_notes），供测试与调参
        self.last_metrics = {}
        # 最近一段是否判为哼唱（供声纹按域选模板；段结束后仍保留）
        self.last_segment_hum = False


@singleton
class TBHumDetect:
    """哼唱检测器（单例，按源分状态）：满 hum_collect_sec 判定并定歌，段结束触发接唱"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBMeowSongsConfig()
        self.sv_config = SenseVoiceConfig()
        self._lock = threading.RLock()
        self._states = {}

    def _state(self, sid: str) -> _SourceState:
        """取（或建）指定音频源的状态（内部加锁，可重入）"""
        sid = sid or DEFAULT_SOURCE
        with self._lock:
            st = self._states.get(sid)
            if st is None:
                st = _SourceState()
                self._states[sid] = st
            return st

    def feed(self, frame: bytes, sid: str = DEFAULT_SOURCE):
        """喂一帧 16k 单声道 PCM：按源累积，满 hum_collect_sec 立即判定，段结束兜底"""
        try:
            arr = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
            if arr.size == 0:
                return
            rms = float(np.sqrt(np.mean(arr ** 2)))

            with self._lock:
                st = self._state(sid)
                now = time.time()
                # 有效语音：能量 >= SenseVoice VAD 阈值
                if rms >= self.sv_config.energy_threshold:
                    if st.speech_start == 0.0:
                        st.speech_start = now
                        # 新段开始：先按"非哼唱"算，判定通过后再置位，
                        # 避免上一段的结论残留到这一段（说话被拿去比哼唱模板）
                        st.last_segment_hum = False
                    st.last_sound = now
                else:
                    # 静音超过 SenseVoice silence_threshold → 段结束，分析并清空重来
                    if st.speech_start > 0.0 and now - st.last_sound >= self.sv_config.silence_threshold:
                        self._finish_segment(sid)
                        # 段结束即定格本段结论（短段也要写，避免把上一段的结论带过来）
                        st.last_segment_hum = st.segment_triggered
                        st.speech_start = 0.0
                        st.last_sound = 0.0
                        # 段结束清空缓冲，保证下一段分析的只有当前语音
                        st.buffer.clear()
                        st.buf_samples = 0
                        st.buf_seconds = 0.0
                        st.checked_at_collect = False
                        st.segment_triggered = False
                        # 注意：last_hum_duration / last_event_type / need_discard 不在此清空，
                        # 需保留给 toolbox_audio 在 seq 变化后异步读取（否则 sing 事件的时长/类型/丢弃标志会丢失）

                # 语音段进行中才累积：只保留当前段的音频（有声 + 段内短静音）
                if st.speech_start > 0.0:
                    st.buffer.append(arr)
                    st.buf_samples += arr.size
                    st.buf_seconds = st.buf_samples / SAMPLE_RATE
                    # 满 hum_collect_sec 立即判定 + 定歌（不等静音段结束），只判一次
                    if (not st.checked_at_collect
                            and st.buf_seconds >= self.config.hum_collect_sec):
                        st.checked_at_collect = True
                        if self._analyze_buffer(sid):
                            st.segment_triggered = True
                            st.need_discard = True
                            st.last_event_type = "lock"
                            st.last_segment_hum = True
                            self._trigger_lock(sid)
        except Exception:
            self.log.exception(f"[HumDetect] 喂帧异常 sid={sid}")

    def _finish_segment(self, sid: str):
        """一段有效语音结束：触发接唱事件（已定歌则只定位，未定歌则兜底匹配）"""
        st = self._state(sid)
        if st.speech_start == 0.0:
            return
        # 用当前段累积的语音时长判断（不含段尾静音）
        if st.buf_seconds < self.config.hum_collect_sec:
            return
        # 已定歌 → 段结束触发接唱（携带完整音频，供未锁定时兜底匹配）
        if st.segment_triggered:
            st.last_event_type = "sing"
            self._trigger_sing(sid, need_match=True)
            return
        # 满 hum_collect_sec 未通过 → 段结束兜底判定 + 接唱（无锁定结果，需匹配）
        if self._analyze_buffer(sid):
            st.segment_triggered = True
            st.need_discard = True
            st.last_event_type = "sing"
            self._trigger_sing(sid, need_match=True)

    def _analyze_buffer(self, sid: str):
        """判定当前累积缓冲是否为哼唱（pyin fl1024），返回 bool，不触发匹配"""
        try:
            st = self._state(sid)
            with self._lock:
                if st.buf_seconds < self.config.hum_collect_sec:
                    return False
                audio = np.concatenate(list(st.buffer))
            if audio.size < int(SAMPLE_RATE * self.config.hum_collect_sec):
                return False
            import librosa
            f0, voiced_flag, voiced_prob = librosa.pyin(
                audio.astype(np.float32) / 32768.0,
                fmin=F0_MIN, fmax=F0_MAX,
                sr=SAMPLE_RATE, frame_length=JUDGE_FRAME_LENGTH, hop_length=JUDGE_HOP,
            )
            # 有声帧：pyin 判定有声且置信度足够（静音帧不参与统计）
            weight = np.clip((voiced_prob - 0.30) / 0.50, 0.0, 1.0)
            voiced = voiced_flag & (weight > 0.05)
            if int(voiced.sum()) < 3:
                with self._lock:
                    st.last_metrics = {
                        "ratio": 0.0, "stable_ratio": 0.0, "unique_notes": 0,
                        "voiced_frames": int(voiced.sum()), "total_frames": int(f0.size),
                    }
                return False
            ratio = float(voiced.mean())
            midi = 12.0 * np.log2(f0[voiced] / 440.0) + 69.0
            # 稳定帧占比：相邻帧音高差 < 阈值半音的帧占比
            # （哼唱音符内音高稳定、占比高；说话音高连续乱飘、占比低）
            abs_diff = np.abs(np.diff(midi))
            stable_ratio = float(np.mean(abs_diff < self.config.f0_stable_half_step))
            unique_notes = len(np.unique(np.round(midi).astype(int)))
            with self._lock:
                st.last_metrics = {
                    "ratio": round(ratio, 3),
                    "stable_ratio": round(stable_ratio, 3),
                    "unique_notes": unique_notes,
                    "voiced_frames": int(voiced.sum()),
                    "total_frames": int(f0.size),
                }
            return (
                ratio >= self.config.f0_voiced_ratio
                and stable_ratio >= self.config.f0_stable_ratio
                and unique_notes >= self.config.f0_unique_notes
            )
        except Exception:
            self.log.exception(f"[HumDetect] 完整分析异常 sid={sid}")
            return False

    def _trigger_lock(self, sid: str):
        """定歌：用 hum_collect_sec 快照触发匹配事件（供 toolbox_audio 落盘匹配）"""
        st = self._state(sid)
        with self._lock:
            audio = np.concatenate(list(st.buffer))
            if audio.size < int(SAMPLE_RATE * self.config.hum_collect_sec):
                return
            st.last_hum_audio = audio
            st.last_hum_duration = st.buf_seconds
            st.hum_event_seq += 1

    def _trigger_sing(self, sid: str, need_match=False):
        """段结束接唱：触发接唱事件（need_match=True 时携带完整音频供兜底匹配）"""
        st = self._state(sid)
        with self._lock:
            audio = None
            if need_match:
                audio = np.concatenate(list(st.buffer))
                if audio.size < int(SAMPLE_RATE * self.config.hum_collect_sec):
                    return
            st.last_hum_audio = audio
            st.last_hum_duration = st.buf_seconds  # 完整时长 T
            st.hum_event_seq += 1

    def consume_hum_audio(self, sid: str = DEFAULT_SOURCE):
        """取出最近一次判定成功的哼唱音频（float32 数组）并清除，供落盘匹配"""
        with self._lock:
            st = self._state(sid)
            audio = st.last_hum_audio
            st.last_hum_audio = None
            return audio

    def get_hum_event_seq(self, sid: str = DEFAULT_SOURCE):
        """返回指定源当前哼唱段完成事件序号（toolbox_audio 据此检测新事件）"""
        with self._lock:
            return self._state(sid).hum_event_seq

    def get_last_hum_duration(self, sid: str = DEFAULT_SOURCE):
        """返回指定源最近一段哼唱的时长（秒），供接唱定位 offset+时长"""
        with self._lock:
            return self._state(sid).last_hum_duration

    def get_last_event_type(self, sid: str = DEFAULT_SOURCE):
        """返回指定源最近一次触发的事件类型（"lock" 或 "sing"）"""
        with self._lock:
            return self._state(sid).last_event_type

    def is_last_segment_hum(self, sid: str = DEFAULT_SOURCE):
        """返回指定源最近一段是否判定为哼唱（供声纹按域选模板）"""
        with self._lock:
            return bool(self._state(sid).last_segment_hum)

    def get_last_metrics(self, sid: str = DEFAULT_SOURCE):
        """返回指定源最近一次判定的指标快照（ratio / stable_ratio / unique_notes 等）"""
        with self._lock:
            return dict(self._state(sid).last_metrics)

    def get_and_clear_need_discard(self, sid: str = DEFAULT_SOURCE):
        """读取并复位指定源的「需要丢弃哼唱 ASR final」标志"""
        with self._lock:
            st = self._state(sid)
            v = st.need_discard
            st.need_discard = False
            return v

    def reset(self, sid: str):
        """丢弃指定源的全部状态（源被关闭/会话重建时调用）"""
        with self._lock:
            self._states.pop(sid or DEFAULT_SOURCE, None)
