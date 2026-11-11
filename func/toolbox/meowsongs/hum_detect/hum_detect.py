# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/hum_detect/hum_detect.py
# 哼唱检测：有效语音累积满 hum_collect_sec 后立即判定并定歌（lock 事件），段结束触发接唱（sing 事件）
# 每个音频源（mic / loopback / inject）各持一份独立状态，互不干扰
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

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
        "last_segment_hum", "epoch", "segment_end_ts",
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
        # 段世代：每开一段 +1；异步判定回来时用它确认结论仍属于当前段
        self.epoch = 0
        # 本段结束时刻（0=段进行中）：异步判定据此判断结论是否赶在 ASR final 之前
        self.segment_end_ts = 0.0


@singleton
class TBHumDetect:
    """哼唱检测器（单例，按源分状态）：满 hum_collect_sec 判定并定歌，段结束触发接唱"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBMeowSongsConfig()
        self.sv_config = SenseVoiceConfig()
        self._lock = threading.RLock()
        self._states = {}
        # pyin 判定只在这个单线程池里跑：喂帧主链（事件循环）不再被长音频阻塞，
        # 单线程同时保证同一源的判定按提交顺序完成。
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hum-judge")
        self._pending = {}   # sid -> (epoch, Future)：最近一次提交的判定
        # 按源单调递增的世代号：段开始/状态被重置都会 +1。
        # 放在单例上而不是 state 里，是为了 reset 后新建的 state 也不会复用旧世代，
        # 否则线程池里上一段的判定可能误写进重建后的同号 state。
        self._gen = {}       # sid -> int
        # 收句读结论时最多等判定这么久（只有 ≥hum_collect_sec 的长段才可能有未完成判定）
        self.HUM_VERDICT_WAIT = 0.12
        # 收句判定落地窗口：只有赶在本句 ASR final（≈段结束后 0.2~1.0s）之前落地的
        # 「丢弃本句 ASR」才有效。晚于窗口说明本句已经送出去了，此时再置位只会
        # 把下一句的识别结果丢掉，所以宁可不置位。
        self.DISCARD_WINDOW = 1.2

    def _state(self, sid: str) -> _SourceState:
        """取（或建）指定音频源的状态（内部加锁，可重入）"""
        sid = sid or DEFAULT_SOURCE
        with self._lock:
            st = self._states.get(sid)
            if st is None:
                st = _SourceState()
                st.epoch = self._gen.get(sid, 0)
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
                        # 段世代 +1：上一段还在线程池里的判定回来会被丢弃
                        self._gen[sid] = self._gen.get(sid, 0) + 1
                        st.epoch = self._gen[sid]
                        st.segment_end_ts = 0.0
                        self._pending.pop(sid, None)
                    st.last_sound = now
                else:
                    # 静音超过 SenseVoice silence_threshold → 段结束，分析并清空重来
                    if st.speech_start > 0.0 and now - st.last_sound >= self.sv_config.silence_threshold:
                        self._finish_segment(sid)
                        # 段结束即定格本段结论（短段也要写，避免把上一段的结论带过来）
                        st.last_segment_hum = st.segment_triggered
                        st.speech_start = 0.0
                        st.last_sound = 0.0
                        st.segment_end_ts = now
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
                    # 判定本身（pyin）丢线程池：锁内只做一次快照拷贝，不阻塞喂帧
                    if (not st.checked_at_collect
                            and st.buf_seconds >= self.config.hum_collect_sec):
                        st.checked_at_collect = True
                        self._submit_judge(sid, np.concatenate(list(st.buffer)),
                                           st.epoch, "lock", st.buf_seconds)
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
        # 满 hum_collect_sec 的定歌判定还在线程池里跑：等它回来即可，不再重复跑一次 pyin
        pending = self._pending.get(sid)
        if pending is not None and pending[0] == st.epoch and not pending[1].done():
            return
        # 满 hum_collect_sec 未通过 → 段结束兜底判定 + 接唱（判定同样丢线程池，不阻塞喂帧）
        self._submit_judge(sid, np.concatenate(list(st.buffer)),
                           st.epoch, "sing", st.buf_seconds)

    def _submit_judge(self, sid: str, audio, epoch: int, kind: str, duration: float):
        """把一次 pyin 判定提交到单线程池（保序）；结果回写前校验段世代"""
        try:
            fut = self._executor.submit(self._judge, sid, audio, epoch, kind, duration)
        except Exception:
            self.log.exception(f"[HumDetect] 提交判定失败 sid={sid}")
            return
        self._pending[sid] = (epoch, fut)

    def _judge(self, sid: str, audio, epoch: int, kind: str, duration: float) -> bool:
        """线程池任务：跑 pyin 判定并回写状态（段已更换则只返回结论、不写状态）"""
        try:
            ok, metrics = self._analyze_audio(audio)
        except Exception:
            self.log.exception(f"[HumDetect] 完整分析异常 sid={sid}")
            return False
        with self._lock:
            st = self._state(sid)
            if st.epoch != epoch:
                return ok
            st.last_metrics = metrics
            if not ok:
                return False
            st.last_segment_hum = True
            st.last_hum_audio = audio
            st.last_hum_duration = duration
            # 只有赶在本句 ASR final 之前落地的结论才记「丢弃本句 ASR」；
            # 晚了就不再置位，否则会把下一句的识别结果吃掉
            if self._discard_in_time(st):
                st.need_discard = True
            # 段已结束才回来的定歌判定：段已收句，直接按接唱事件落地，
            # 但不能写 segment_triggered（会把「已定歌」漏进下一段）
            if kind == "lock" and st.speech_start <= 0.0:
                st.last_event_type = "sing"
                st.hum_event_seq += 1
                return ok
            if kind == "lock":
                st.segment_triggered = True
                st.last_event_type = "lock"
            else:
                st.last_event_type = "sing"
            st.hum_event_seq += 1
        return ok

    def _discard_in_time(self, st) -> bool:
        """判定结论是否仍赶在本句 ASR final 之前（段结束后超过窗口就不算）"""
        if st.segment_end_ts <= 0.0:
            return True     # 段还在进行中（7s 定歌），结论本来就早于 final
        return (time.time() - st.segment_end_ts) <= self.DISCARD_WINDOW

    def _analyze_audio(self, audio):
        """纯判定一段音频是否为哼唱（pyin fl1024），返回 (ok, metrics)。

        不读写任何状态，可安全地在线程池里执行；调用方负责把 metrics 写回状态。
        """
        empty = {"ratio": 0.0, "stable_ratio": 0.0, "unique_notes": 0,
                 "voiced_frames": 0, "total_frames": 0}
        try:
            if audio is None or audio.size < int(SAMPLE_RATE * self.config.hum_collect_sec):
                return False, empty
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
                metrics = dict(empty, voiced_frames=int(voiced.sum()),
                               total_frames=int(f0.size))
                return False, metrics
            ratio = float(voiced.mean())
            midi = 12.0 * np.log2(f0[voiced] / 440.0) + 69.0
            # 稳定帧占比：相邻帧音高差 < 阈值半音的帧占比
            # （哼唱音符内音高稳定、占比高；说话音高连续乱飘、占比低）
            abs_diff = np.abs(np.diff(midi))
            stable_ratio = float(np.mean(abs_diff < self.config.f0_stable_half_step))
            unique_notes = len(np.unique(np.round(midi).astype(int)))
            metrics = {
                "ratio": round(ratio, 3),
                "stable_ratio": round(stable_ratio, 3),
                "unique_notes": unique_notes,
                "voiced_frames": int(voiced.sum()),
                "total_frames": int(f0.size),
            }
            ok = (
                ratio >= self.config.f0_voiced_ratio
                and stable_ratio >= self.config.f0_stable_ratio
                and unique_notes >= self.config.f0_unique_notes
            )
            return ok, metrics
        except Exception:
            self.log.exception("[HumDetect] 完整分析异常")
            return False, empty

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
        """返回指定源最近一段是否判定为哼唱（供声纹按域选模板）

        pyin 已在线程池里跑：若本段结论还在计算中（只有 ≥hum_collect_sec 的长段会这样），
        最多等 HUM_VERDICT_WAIT 秒，避免收到段尾时结论还没回来而误用说话模板。
        """
        sid = sid or DEFAULT_SOURCE
        with self._lock:
            st = self._state(sid)
            epoch = st.epoch
            pending = self._pending.get(sid)
        if pending is not None and pending[0] == epoch and not pending[1].done():
            try:
                pending[1].result(timeout=self.HUM_VERDICT_WAIT)
            except Exception:
                pass
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
        sid = sid or DEFAULT_SOURCE
        with self._lock:
            # 世代继续递增：重建后的 state 不会与线程池里旧判定同号
            self._gen[sid] = self._gen.get(sid, 0) + 1
            self._pending.pop(sid, None)
            self._states.pop(sid, None)
