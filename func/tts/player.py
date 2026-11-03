# func/tts/player.py
# 音频播放器：mpv 子进程播放（替代 pyaudio），支持立即打断
import os
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from func.pipeline.tts_vts import TtsVtsBridge
from func.pipeline.tts_desktopet import TtsDesktopetBridge
from func.pipeline.audio_state import AudioState

# 项目根目录下的 mpv.exe
MPV_PATH = str(Path(__file__).resolve().parents[2] / "mpv.exe")

# 补静音粒度（毫秒）
SILENCE_TICK_MS = 20
# 段首淡入时长（毫秒）：消除段与段拼接处的振幅突变
FADE_IN_MS = 5.0


def _set_playing(playing):
    """同时驱动 VTS 与桌宠的表现桥接（嘴部开合/身体摆动），并更新全局音频播放状态"""
    TtsVtsBridge().set_playing(playing)
    TtsDesktopetBridge().set_playing(playing)
    AudioState().set_playing(playing)


def fade_in(data: bytes, samplerate: int, channels: int = 1, ms: float = FADE_IN_MS) -> bytes:
    """对一段 int16 PCM 的头部做线性淡入"""
    if not data or ms <= 0:
        return data
    try:
        n_ch = max(1, int(channels or 1))
        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        frames = arr.size // n_ch
        k = min(int(int(samplerate or 32000) * ms / 1000.0), frames)
        if k <= 0:
            return data
        ramp = np.linspace(0.0, 1.0, k, dtype=np.float32)
        if n_ch > 1:
            ramp = np.repeat(ramp, n_ch)
        arr[:k * n_ch] *= ramp
        return np.clip(arr, -32768, 32767).astype(np.int16).tobytes()
    except Exception:
        return data


def fade_out(data: bytes, samplerate: int, channels: int = 1, ms: float = FADE_IN_MS) -> bytes:
    """对一段 int16 PCM 的尾部做线性淡出

    句尾最后几个采样哪怕只有几百，直接切到静音也是一下"啪"的台阶；
    给 20~40ms 的斜坡下去，收尾就自然了。
    """
    if not data or ms <= 0:
        return data
    try:
        n_ch = max(1, int(channels or 1))
        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        frames = arr.size // n_ch
        k = min(int(int(samplerate or 32000) * ms / 1000.0), frames)
        if k <= 0:
            return data
        ramp = np.linspace(1.0, 0.0, k, dtype=np.float32)
        if n_ch > 1:
            ramp = np.repeat(ramp, n_ch)
        arr[-k * n_ch:] *= ramp
        return np.clip(arr, -32768, 32767).astype(np.int16).tobytes()
    except Exception:
        return data


class AudioPlayer:
    """mpv 子进程音频播放器，支持立即打断

    - 流式播放复用同采样率/声道的常驻 mpv 进程，短句之间不反复启停；
    - 写入不做节流，靠管道自带缓冲吸收网络抖动（约 1s）；
    - 空闲时由调用方（TTsCore）调 shutdown() 关闭常驻进程。
    """

    def __init__(self):
        self._proc = None
        self._sr = None
        self._channels = None
        self._lock = threading.Lock()
        # 写串行锁：保证播放线程写入与 stop() 不交错
        self._write_lock = threading.Lock()
        # 置位后正在写的播放线程立即放手，保证打断及时
        self._stopping = threading.Event()
        # 最后一次写入的时间：用于延迟关闭常驻进程（关闭声卡会有一声"嗒"）
        self._last_ts = 0.0
        # 对外播报状态（嘴型/loopback 静音）：进程留着不等于"还在说话"
        self._ui_playing = False

    def _touch(self):
        self._last_ts = time.monotonic()

    def _ui_set(self, playing: bool):
        """只在状态真正变化时驱动表现层，避免重复调用"""
        if self._ui_playing == playing:
            return
        self._ui_playing = playing
        _set_playing(playing)

    # ==================== 进程生命周期 ====================

    @staticmethod
    def _exists():
        return os.path.exists(MPV_PATH)

    @staticmethod
    def _base_cmd():
        return [
            MPV_PATH,
            "--no-config",
            "--no-video",
            "--no-terminal",
            "--idle=no",
            "--force-window=no",
        ]

    def _detach_locked(self):
        """取走当前进程并清空状态（调用方持锁，不在此关闭进程）"""
        proc = self._proc
        self._proc = None
        self._sr = None
        self._channels = None
        return proc

    @staticmethod
    def _kill_proc(proc, graceful=False):
        """graceful=只关 stdin 让 mpv 播完剩余缓冲自然退出；否则直接 terminate"""
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        if graceful:
            return
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _close_locked(self, graceful=False):
        """关闭当前 mpv 进程（调用方持锁，不在此等待退出）"""
        self._kill_proc(self._detach_locked(), graceful)

    @staticmethod
    def _hard_kill(proc):
        """硬停止：先 terminate 再关 stdin。

        播放线程可能正阻塞在管道写满的 write() 上：先让对端消失，
        阻塞的写会立刻报错返回；反过来先 close(stdin) 容易卡在写锁上。
        """
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass

    @staticmethod
    def _wait_quit(proc, timeout=1.5):
        """等 mpv 播完缓冲自然退出，超时才 terminate"""
        if proc is None:
            return
        try:
            proc.wait(timeout=timeout)
            return
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=1)
        except Exception:
            pass

    # ==================== 写入 ====================

    def _write_raw(self, data: bytes) -> bool:
        """把字节写进 mpv stdin，返回 False 表示已停止/失败"""
        if not data:
            return True
        with self._lock:
            proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return False
        try:
            with self._write_lock:
                if proc.poll() is not None or proc.stdin is None:
                    return False
                proc.stdin.write(data)
                proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            # 被打断时 mpv 已终止，写入失败视为正常停止
            return False

    def _write_bytes(self, data: bytes) -> bool:
        if not data:
            return True
        if self._stopping.is_set() or not self.is_playing():
            return False
        self._touch()
        return self._write_raw(data)

    def _silence_bytes(self, ms: float) -> bytes:
        """按当前采样率/声道生成静音字节"""
        with self._lock:
            sr = self._sr or 32000
            ch = self._channels or 1
        n = int(sr * ch * 2 * (float(ms) / 1000.0))
        return b"\x00" * max(0, n)

    # ==================== 对外接口 ====================

    def play_file(self, file_path: str, volume: float = 1.0) -> bool:
        """阻塞播放音频文件，返回 True 表示自然播完，False 表示被打断/失败"""
        if not self._exists() or not os.path.exists(file_path):
            return False
        cmd = self._base_cmd() + [f"--volume={int(volume * 100)}", os.path.abspath(file_path)]
        with self._lock:
            old = self._detach_locked()
        if old is not None:
            self._kill_proc(old, graceful=False)
            self._wait_quit(old, timeout=0.5)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"启动 mpv 失败: {e}")
            return False
        with self._lock:
            self._proc = proc
        self._ui_set(True)
        try:
            proc.wait()
        except Exception:
            pass
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None
                    self._sr = None
                    self._channels = None
            self._ui_set(False)
        return proc.returncode == 0

    def open_stream(self, samplerate: int = 32000, channels: int = 1) -> bool:
        """打开（或复用）mpv 裸 PCM 流式播放，从 stdin 读，返回是否成功"""
        if not self._exists():
            return False
        samplerate = int(samplerate)
        channels = int(channels)
        with self._lock:
            proc = self._proc
            # 已有同参数常驻进程则直接复用
            if proc is not None and proc.poll() is None \
                    and self._sr == samplerate and self._channels == channels:
                self._touch()
                self._ui_set(True)
                return True
            old = proc
            if proc is not None:
                self._detach_locked()
        if old is not None:
            # 换参数（少见）：让旧进程播完收尾，避免两路叠着出声
            self._kill_proc(old, graceful=True)
            self._wait_quit(old, timeout=1.0)
        with self._lock:
            cmd = self._base_cmd() + [
                "--demuxer=rawaudio",
                "--demuxer-rawaudio-format=s16le",
                f"--demuxer-rawaudio-channels={channels}",
                f"--demuxer-rawaudio-rate={samplerate}",
                "--audio-buffer=0.2",
                "--demuxer-readahead-secs=0.5",
                "--cache=no",
                "-",
            ]
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"启动 mpv 失败: {e}")
                return False
            self._proc = proc
            self._sr = samplerate
            self._channels = channels
            self._stopping.clear()
            self._touch()
        self._ui_set(True)
        return True

    def write(self, data: bytes, volume: float = 1.0) -> bool:
        """向 mpv stdin 写入 PCM 字节，返回 False 表示已停止/失败"""
        if not data:
            return True
        if volume != 1.0:
            try:
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                arr = (arr * volume).clip(-32768, 32767).astype(np.int16)
                data = arr.tobytes()
            except Exception:
                pass
        return self._write_bytes(data)

    def write_silence(self, ms: float) -> bool:
        """写入静音（段间停顿用）"""
        remaining = float(ms)
        while remaining > 0:
            step = min(float(SILENCE_TICK_MS), remaining)
            if not self._write_bytes(self._silence_bytes(step)):
                return False
            remaining -= step
        return True

    def shutdown(self):
        """空闲关闭常驻 mpv 进程：关 stdin 让 mpv 播完剩余缓冲后自然退出"""
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            self._close_locked(graceful=True)
        self._ui_set(False)
        # 管道里可能还有约 1s 音频：等它播完退出，避免与下一段叠着出声
        self._wait_quit(proc, timeout=3.0)

    def mark_idle(self):
        """本轮说完了：对外状态立刻置"未播放"（嘴型闭嘴、loopback 解除静音），
        但 mpv 进程/声卡先留着，避免关声卡那一声"嗒"贴在句尾。
        """
        self._ui_set(False)

    def shutdown_if_idle(self, idle_sec: float = 120.0):
        """空闲够久了才真正关闭常驻 mpv

        关掉 mpv 就等于关掉声卡，某些机器上会"嗒"一声（电流声/爆音）。
        每句话播完就关，那一声就贴在句尾，听起来像被掐断；
        所以先让进程挂着（声卡保持打开），等真的没人说话一段时间再关。
        """
        if self.is_playing() and (time.monotonic() - self._last_ts) < idle_sec:
            return
        self.shutdown()

    def stop(self):
        """立即停止播放并退出常驻进程"""
        with self._lock:
            proc = self._proc
            if proc is not None:
                self._detach_locked()
        if proc is None:
            return
        self._stopping.set()
        self._hard_kill(proc)
        self._ui_set(False)
        self._wait_quit(proc, timeout=0.5)

    def is_playing(self) -> bool:
        """返回当前是否有音频正在播放"""
        with self._lock:
            proc = self._proc
        return proc is not None and proc.poll() is None
