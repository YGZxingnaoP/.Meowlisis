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

# 写节流提前量（秒）：最多只把「播放头 + LEAD_SECONDS」的音频写进不可撤回的管道。
# 抖动缓冲由调用方队列承担（可瞬间丢弃），因此该值只影响打断时要丢弃的音频量；
# 首块音频总是立即写入，所以它不影响首字出声时间。
LEAD_SECONDS = 0.2
# 启动热身期（秒）：mpv 从 spawn 到真正出声约 0.2s，这段时间播放头没动，
# 节流时钟必须先扣掉它，否则「已写未播」会被系统性高估、打断残留随之变大。
WARMUP_SECONDS = 0.2
# 补静音粒度（毫秒）：没有数据时按此粒度写零，让 mpv 始终有内容可播
SILENCE_TICK_MS = 20
# 段首淡入时长（毫秒）：消除段与段拼接处的振幅突变
FADE_IN_MS = 5.0
# 段尾淡出时长（毫秒）：把语音尾巴平滑落到 0，避免直接切到静音/关闭声卡时爆音
TAIL_FADE_MS = 15.0
# 打断淡出时长（毫秒）
FADE_OUT_MS = 60.0


def _set_playing(playing):
    """同时驱动 VTS 与桌宠的表现桥接（嘴部开合/身体摆动），并更新全局音频播放状态"""
    TtsVtsBridge().set_playing(playing)
    TtsDesktopetBridge().set_playing(playing)
    AudioState().set_playing(playing)


def fade_in(data: bytes, samplerate: int, channels: int = 1, ms: float = FADE_IN_MS) -> bytes:
    """对一段 int16 PCM 的头部做线性淡入，消除段与段拼接处的振幅突变。"""
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


class AudioPlayer:
    """mpv 子进程音频播放器，支持立即打断

    - 流式播放（open_stream/write）会复用同采样率/声道的常驻 mpv 进程，
      短句之间不再反复启停进程，避免长间隔；
    - 写入按「播放头 + LEAD_SECONDS」节流：不可撤回的管道里只留一小段提前量，
      打断时丢弃得少，接一段淡出即可自然收尾；
    - 没有数据时用 write_silence 补静音占位，mpv 不会 underrun（卡顿/爆音）；
    - 空闲时由调用方（TTsCore）调 shutdown() 真正关闭常驻进程。
    """

    def __init__(self):
        self._proc = None
        self._sr = None
        self._channels = None
        self._lock = threading.Lock()
        # 写串行锁：保证「播放线程写音频」与「stop() 写淡出」不会交错
        self._write_lock = threading.Lock()
        # 停止标志：置位后正在写的播放线程立即放手，保证打断及时
        self._stopping = threading.Event()
        # 写节流状态（每个 mpv 进程一份，跨句复用不重置）
        self._bytes_per_sec = 0
        self._lead_bytes = 0
        self._written = 0
        self._epoch = 0.0
        self._last_sample = 0
        # 上一个已软关闭、正在自行收尾的进程（避免新进程和它的尾巴叠着出声）
        self._prev = None

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

    def _reset_pace_locked(self):
        """清空写节流状态（调用方持锁）"""
        self._bytes_per_sec = 0
        self._lead_bytes = 0
        self._written = 0
        self._epoch = 0.0
        self._last_sample = 0

    def _detach_locked(self):
        """取走当前进程并清空状态（调用方持锁，不在此关闭进程）"""
        proc = self._proc
        self._proc = None
        self._sr = None
        self._channels = None
        self._reset_pace_locked()
        return proc

    @staticmethod
    def _kill_proc(proc, graceful=False):
        """关闭进程：graceful=只关 stdin 让 mpv 播完剩余缓冲自然退出；否则直接 terminate"""
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
        """硬/软关闭当前 mpv 进程（调用方持锁，不在此等待退出）"""
        self._kill_proc(self._detach_locked(), graceful)

    @staticmethod
    def _wait_quit(proc, timeout=1.5):
        """软关闭后等 mpv 播完缓冲自然退出，超时才 terminate"""
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

    # ==================== 写节流 ====================

    def _room_bytes(self):
        """还能写多少字节：保证「已写未播」不超过 LEAD_SECONDS。

        mpv 卡住（underrun）时播放头不会前进，此时最多也只允许领先 lead，
        避免一次性把大段音频灌进不可撤回的管道（那样打断只能硬切，必有爆音）。
        """
        if self._bytes_per_sec <= 0:
            return 0
        elapsed = time.monotonic() - self._epoch - WARMUP_SECONDS
        if elapsed < 0:
            # mpv 刚起还没出声：播放头仍在原点
            elapsed = 0.0
        unplayed = self._written - int(elapsed * self._bytes_per_sec)
        if unplayed < 0:
            unplayed = 0
        elif unplayed > self._lead_bytes:
            unplayed = self._lead_bytes
        return self._lead_bytes - unplayed

    def _track_last_sample(self, data):
        """记录最后写入的样本值（音量缩放后），供淡出时接上波形"""
        if not data:
            return
        off = len(data) - 2 if len(data) % 2 == 0 else len(data) - 3
        if off < 0:
            return
        try:
            self._last_sample = int.from_bytes(data[off:off + 2], "little", signed=True)
        except Exception:
            pass

    def _write_raw(self, data: bytes) -> bool:
        """把字节直接写进 mpv stdin（不节流），返回 False 表示已停止/失败"""
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
            # 被 stop 打断时 mpv 进程已终止，写入失败视为正常停止
            return False

    def _write_paced(self, data: bytes) -> bool:
        """按「播放头 + lead」节流写入，返回 False 表示已停止/失败"""
        if not data:
            return True
        if self._bytes_per_sec <= 0:
            return False
        pos = 0
        total = len(data)
        while pos < total:
            if self._stopping.is_set() or not self.is_playing():
                return False
            room = self._room_bytes()
            if room <= 0:
                time.sleep(0.005)
                continue
            piece = data[pos:pos + min(total - pos, room)]
            if not self._write_raw(piece):
                return False
            self._written += len(piece)
            self._track_last_sample(piece)
            pos += len(piece)
        return True

    def _silence_bytes(self, ms: float) -> bytes:
        """按当前采样率/声道生成静音字节"""
        with self._lock:
            sr = self._sr or 32000
            ch = self._channels or 1
        n = int(sr * ch * 2 * (float(ms) / 1000.0))
        return b"\x00" * max(0, n)

    @staticmethod
    def _fade_bytes(last_value, sr, ch, ms) -> bytes:
        """从 last_value 线性降到 0 的淡出字节（int16，按声道复制）"""
        n_ch = max(1, int(ch or 1))
        k = max(2, int(int(sr or 32000) * float(ms) / 1000.0))
        ramp = np.linspace(float(int(last_value or 0)), 0.0, k)
        if n_ch > 1:
            ramp = np.repeat(ramp, n_ch)
        return np.clip(ramp, -32768, 32767).astype(np.int16).tobytes()

    def fade_out_tail(self, ms: float = TAIL_FADE_MS) -> bool:
        """在流尾接一段淡出：与语音波形连续，落点为零，之后切静音/关声卡都不会爆音"""
        with self._lock:
            proc = self._proc
            sr = self._sr or 32000
            ch = self._channels or 1
            last = self._last_sample
        if proc is None or proc.poll() is not None:
            return False
        try:
            data = self._fade_bytes(last, sr, ch, ms)
        except Exception:
            return False
        return self._write_paced(data)

    def _send_fade(self, proc, sr, ch, last, ms=FADE_OUT_MS, timeout=0.15) -> bool:
        """给指定进程追加一段淡出（打断用；流尾连续，不爆音）"""
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return False
        try:
            data = self._fade_bytes(last, sr, ch, ms)
        except Exception:
            return False
        if not self._write_lock.acquire(timeout=timeout):
            # 管道卡住（mpv 未消费）：放弃淡出，交给调用方强关，保证打断不悬挂
            return False
        try:
            if proc.poll() is not None or proc.stdin is None:
                return False
            proc.stdin.write(data)
            proc.stdin.flush()
            return True
        except Exception:
            return False
        finally:
            self._write_lock.release()

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
        _set_playing(True)
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
                    self._reset_pace_locked()
            _set_playing(False)
        return proc.returncode == 0

    def open_stream(self, samplerate: int = 32000, channels: int = 1) -> bool:
        """打开（或复用）mpv 裸 PCM 流式播放，从 stdin 读，返回是否成功"""
        if not self._exists():
            return False
        samplerate = int(samplerate)
        channels = int(channels)
        with self._lock:
            proc = self._proc
            # 已有同参数常驻进程则直接复用，避免短句之间反复启停
            if proc is not None and proc.poll() is None \
                    and self._sr == samplerate and self._channels == channels:
                return True
            old = proc
            old_sr = self._sr
            old_ch = self._channels
            old_last = self._last_sample
            if proc is not None:
                self._detach_locked()
        if old is not None:
            # 换参数（少见）：先给旧进程接淡出，等它收尾后再起新进程，避免两路叠着出声
            self._send_fade(old, old_sr, old_ch, old_last)
            self._kill_proc(old, graceful=True)
            self._wait_quit(old, timeout=1.0)
        with self._lock:
            prev, self._prev = self._prev, None
        if prev is not None:
            # shutdown() 软关闭的上一进程可能还在播尾音，等它退出再起新的
            self._wait_quit(prev, timeout=0.6)
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
            self._bytes_per_sec = samplerate * channels * 2
            self._lead_bytes = int(self._bytes_per_sec * LEAD_SECONDS)
            self._written = 0
            self._epoch = time.monotonic()
            self._last_sample = 0
            self._stopping.clear()
        _set_playing(True)
        return True

    def write(self, data: bytes, volume: float = 1.0) -> bool:
        """向 mpv stdin 写入 PCM 字节（按播放头节流），返回 False 表示已停止/失败"""
        if not data:
            return True
        # 音量调节（int16 缩放）
        if volume != 1.0:
            try:
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                arr = (arr * volume).clip(-32768, 32767).astype(np.int16)
                data = arr.tobytes()
            except Exception:
                pass
        return self._write_paced(data)

    def write_silence(self, ms: float) -> bool:
        """向流中写入静音占位（保持 mpv 不断流；段间停顿也走这里）"""
        remaining = float(ms)
        while remaining > 0:
            step = min(float(SILENCE_TICK_MS), remaining)
            if not self._write_paced(self._silence_bytes(step)):
                return False
            remaining -= step
        return True

    def close_stream(self):
        """软关闭：保留常驻 mpv 进程，供下个短句复用（不真正退出）"""
        pass

    def shutdown(self):
        """空闲关闭常驻 mpv 进程：关 stdin 让 mpv 播完剩余缓冲后自然退出（不阻塞播放线程）"""
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            self._close_locked(graceful=True)
            self._prev = proc
        _set_playing(False)

    def stop(self):
        """立即停止播放并退出常驻进程：流式播放先接一段淡出，再让 mpv 自然收尾"""
        with self._lock:
            proc = self._proc
            sr = self._sr or 32000
            ch = self._channels or 1
            last = self._last_sample
            streaming = self._bytes_per_sec > 0
            if proc is not None:
                self._detach_locked()
        if proc is None:
            return
        if not streaming or proc.poll() is not None:
            # 文件播放（歌曲等）没有可续写的 PCM 流：直接停止，不做淡出
            self._stopping.set()
            self._kill_proc(proc, graceful=False)
            _set_playing(False)
            self._wait_quit(proc, timeout=0.5)
            return
        # 先放手：让还在写的播放线程立即退出，避免与淡出写入交错
        self._stopping.set()
        self._send_fade(proc, sr, ch, last)
        self._kill_proc(proc, graceful=True)
        _set_playing(False)
        # 只等它把这一小段淡出播完（≤ lead + 淡出时长），不做长阻塞
        self._wait_quit(proc, timeout=0.8)

    def is_playing(self) -> bool:
        """返回当前是否有音频正在播放"""
        with self._lock:
            proc = self._proc
        return proc is not None and proc.poll() is None
