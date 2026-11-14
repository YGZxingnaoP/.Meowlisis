# -*- coding: utf-8 -*-
# scripts/MossLive-test/mosslive/audio.py
# 实时音频：
#   MicCapture      —— 麦克风采集 16 kHz / 单声道 / PCM16，20 ms 一帧（接口默认上行格式）；
#   PlaybackEngine  —— 下行 48 kHz PCM16 播放队列，按实际播放进度回执
#                      playback.chunk.completed / playback.completed / playback.stopped。
#
# 设备不支持目标采样率时会自动换到设备可用采样率，并在本地重采样，避免直接失败。
# 没有输出设备时退化为“按时长模拟播放”，仍然回执，保证服务端不会卡在等回执。

import queue
import threading
import time

import numpy as np
import pyaudio


def resample_pcm16(data: bytes, src_rate: int, dst_rate: int) -> bytes:
    """线性插值重采样（16bit 单声道）"""
    if not data or src_rate == dst_rate:
        return data
    x = np.frombuffer(data, dtype=np.int16)
    if x.size == 0:
        return b""
    n = max(1, int(round(x.size * float(dst_rate) / float(src_rate))))
    src_index = np.arange(x.size, dtype=np.float32)
    dst_index = np.linspace(0.0, x.size - 1.0, n, dtype=np.float32)
    y = np.interp(dst_index, src_index, x.astype(np.float32))
    return np.clip(y, -32768, 32767).astype(np.int16).tobytes()


def apply_volume(data: bytes, volume: float) -> bytes:
    """音量增益；1.0 原样返回"""
    if not data or abs(volume - 1.0) < 1e-6:
        return data
    x = np.frombuffer(data, dtype=np.int16).astype(np.float32) * float(volume)
    return np.clip(x, -32768, 32767).astype(np.int16).tobytes()


class MicCapture:
    """麦克风采集线程：不断把 16 kHz PCM 交给回调"""

    def __init__(self, device: int, frame_ms: int, target_rate: int, on_frame, console):
        self.device = int(device)
        self.frame_ms = int(frame_ms)
        self.target_rate = int(target_rate)
        self.on_frame = on_frame
        self.console = console
        self._pa = None
        self._stream = None
        self._thread = None
        self._stop = threading.Event()
        self.rate = self.target_rate

    def start(self) -> bool:
        try:
            self._pa = pyaudio.PyAudio()
        except Exception as e:
            self.console.error(f"PyAudio 初始化失败: {e}")
            return False
        dev = self.device if self.device >= 0 else None
        candidates = []
        for rate in (self.target_rate, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 8000):
            if rate not in candidates:
                candidates.append(rate)
        last_err = None
        for rate in candidates:
            try:
                self._stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=rate,
                    input=True,
                    input_device_index=dev,
                    frames_per_buffer=max(160, int(rate * self.frame_ms / 1000)),
                )
                self.rate = rate
                break
            except Exception as e:
                last_err = e
                self._stream = None
        if self._stream is None:
            self.console.error(f"麦克风打开失败（device={self.device}）: {last_err}")
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
            return False

        self.console.info(
            f"麦克风已打开: device={self.device if self.device >= 0 else '默认'} "
            f"{self.rate}Hz{'' if self.rate == self.target_rate else '（本地重采样到 16k）'}"
        )
        self._thread = threading.Thread(target=self._read_loop, name="mosslive-mic", daemon=True)
        self._thread.start()
        return True

    def _read_loop(self):
        frames = max(160, int(self.rate * self.frame_ms / 1000))
        while not self._stop.is_set():
            try:
                raw = self._stream.read(frames, exception_on_overflow=False)
            except Exception as e:
                self.console.warn(f"麦克风读取异常: {e}")
                time.sleep(0.05)
                continue
            if not raw:
                continue
            if self.rate != self.target_rate:
                raw = resample_pcm16(raw, self.rate, self.target_rate)
            try:
                self.on_frame(raw)
            except Exception:
                pass

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None


class _RunState:
    """一个回复（run_id）的播放与回执状态"""

    __slots__ = ("turn_id", "done", "open", "completed", "stopped", "stop", "current_chunk", "played_bytes")

    def __init__(self, turn_id: str):
        self.turn_id = turn_id
        self.done = False
        self.open = 0
        self.completed = False
        self.stopped = False
        self.stop = threading.Event()
        self.current_chunk = None
        self.played_bytes = 0


class PlaybackEngine:
    """下行语音播放：队列 + 回执"""

    def __init__(self, device: int, volume: float, source_rate: int, on_event, console,
                 simulate: bool = False):
        self.device = int(device)
        self.volume = float(volume)
        self.source_rate = int(source_rate)
        self.on_event = on_event          # 回调：接收待发送的 JSON 事件（线程安全由调用方保证）
        self.console = console
        self.simulate = bool(simulate)
        self.rate = self.source_rate
        self._pa = None
        self._stream = None
        self._thread = None
        self._stop = threading.Event()
        self._q = queue.Queue()
        self._lock = threading.Lock()
        self._runs = {}
        self._ctx = None

    # ---------- 生命周期 ----------

    def set_source_rate(self, rate: int):
        self.source_rate = int(rate or 48000)
        self.rate = self.source_rate

    def start(self):
        if not self.simulate:
            try:
                self._pa = pyaudio.PyAudio()
            except Exception as e:
                self.console.warn(f"输出设备初始化失败，改为模拟播放: {e}")
                self.simulate = True
        if not self.simulate:
            dev = self.device if self.device >= 0 else None
            candidates = []
            for rate in (self.source_rate, 48000, 44100, 32000, 24000, 22050, 16000):
                if rate not in candidates:
                    candidates.append(rate)
            last_err = None
            for rate in candidates:
                try:
                    self._stream = self._pa.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=rate,
                        output=True,
                        output_device_index=dev,
                        frames_per_buffer=max(160, int(rate * 0.01)),
                    )
                    self.rate = rate
                    break
                except Exception as e:
                    last_err = e
                    self._stream = None
            if self._stream is None:
                self.console.warn(f"扬声器打开失败，改为模拟播放（仍回执）: {last_err}")
                self.simulate = True
                try:
                    self._pa.terminate()
                except Exception:
                    pass
                self._pa = None
        if self._stream is not None:
            self.console.info(
                f"扬声器已打开: device={self.device if self.device >= 0 else '默认'} {self.rate}Hz"
            )
        self._thread = threading.Thread(target=self._run, name="mosslive-playback", daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    # ---------- 服务端事件 ----------

    def set_context(self, ctx: dict):
        """response.audio.context：配对下一条二进制音频"""
        self._ctx = dict(ctx or {})

    def feed(self, payload: bytes):
        """收到二进制音频：与最近的 context 配对后入队"""
        ctx, self._ctx = self._ctx, None
        if not ctx:
            self.console.warn("收到无 context 的音频二进制，已丢弃")
            return
        run_id = str(ctx.get("run_id") or "")
        turn_id = str(ctx.get("turn_id") or "")
        chunk_id = str(ctx.get("chunk_id") or "")
        if not run_id:
            self.console.warn("音频 context 缺少 run_id，已丢弃")
            return
        with self._lock:
            st = self._runs.get(run_id)
            if st is None:
                st = _RunState(turn_id)
                self._runs[run_id] = st
            st.open += 1
        self._q.put({"run_id": run_id, "turn_id": turn_id, "chunk_id": chunk_id, "data": payload})

    def audio_done(self, run_id: str, turn_id: str):
        """response.audio.done：该回复音频已发完，播放完所有片段后回 playback.completed"""
        with self._lock:
            st = self._runs.get(run_id)
            if st is None:
                st = _RunState(turn_id)
                self._runs[run_id] = st
            st.done = True
        self._maybe_completed(run_id)

    def stop_run(self, run_id: str, turn_id: str):
        """response.audio.stop：立即停止该回复的播放并回报进度"""
        emit = None
        with self._lock:
            st = self._runs.get(run_id)
            if st is None:
                st = _RunState(turn_id)
                self._runs[run_id] = st
            st.stop.set()
            if st.current_chunk is None and not st.stopped and not st.completed:
                st.stopped = True
                played_ms = int(st.played_bytes / 2.0 / max(1, self.rate) * 1000)
                emit = {"action": "playback.stopped", "run_id": run_id,
                        "turn_id": st.turn_id or turn_id, "played_audio_ms": played_ms}
        if emit:
            self.on_event(emit)

    def stop_all(self, reason: str = ""):
        with self._lock:
            run_ids = [rid for rid, st in self._runs.items() if not st.completed and not st.stopped]
        for rid in run_ids:
            with self._lock:
                turn_id = (self._runs.get(rid) or _RunState("")).turn_id
            self.stop_run(rid, turn_id)

    # ---------- 播放线程 ----------

    def _run(self):
        block_ms = 10
        block_bytes = max(320, int(self.rate * block_ms / 1000) * 2)
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            st = self._runs.get(item["run_id"])
            if st is None:
                continue
            with self._lock:
                skip = st.stop.is_set() or st.stopped
                if not skip:
                    st.current_chunk = item["chunk_id"]
                    st.played_bytes = 0
            if skip:
                with self._lock:
                    st.open = max(0, st.open - 1)
                continue

            data = resample_pcm16(item["data"], self.source_rate, self.rate)
            data = apply_volume(data, self.volume)
            aborted = self._play_bytes(data, st, block_bytes)

            with self._lock:
                st.current_chunk = None
                st.open = max(0, st.open - 1)
                if aborted:
                    st.stopped = True
                    played_ms = int(st.played_bytes / 2.0 / max(1, self.rate) * 1000)
                else:
                    played_ms = 0

            if aborted:
                self.on_event({
                    "action": "playback.stopped",
                    "run_id": item["run_id"],
                    "turn_id": item["turn_id"] or st.turn_id,
                    "played_audio_ms": played_ms,
                })
            else:
                self.on_event({
                    "action": "playback.chunk.completed",
                    "run_id": item["run_id"],
                    "turn_id": item["turn_id"] or st.turn_id,
                    "chunk_id": item["chunk_id"],
                })
                self._maybe_completed(item["run_id"])

    def _play_bytes(self, data: bytes, st: _RunState, block_bytes: int) -> bool:
        """按 10ms 块播放；返回是否被中途打断"""
        offset = 0
        total = len(data)
        while offset < total:
            if self._stop.is_set() or st.stop.is_set():
                return True
            piece = data[offset:offset + block_bytes]
            if self._stream is not None:
                try:
                    self._stream.write(piece, exception_on_underflow=False)
                except Exception as e:
                    self.console.warn(f"播放写入失败，改为模拟: {e}")
                    self.simulate = True
                    self._stream = None
            else:
                time.sleep(len(piece) / 2.0 / max(1, self.rate))
            offset += len(piece)
            with self._lock:
                st.played_bytes = offset
        return False

    def _maybe_completed(self, run_id: str):
        emit = False
        with self._lock:
            st = self._runs.get(run_id)
            if st and st.done and st.open <= 0 and not st.completed and not st.stopped:
                st.completed = True
                emit = True
                turn_id = st.turn_id
        if emit:
            self.on_event({
                "action": "playback.completed",
                "run_id": run_id,
                "turn_id": turn_id,
            })
