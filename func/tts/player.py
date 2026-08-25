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

# 项目根目录下的 mpv.exe
MPV_PATH = str(Path(__file__).resolve().parents[2] / "mpv.exe")


def _set_playing(playing):
    """同时驱动 VTS 与桌宠的表现桥接（嘴部开合/身体摆动）"""
    TtsVtsBridge().set_playing(playing)
    TtsDesktopetBridge().set_playing(playing)


class AudioPlayer:
    """mpv 子进程音频播放器，支持立即打断

    - 流式播放（open_stream/write）会复用同采样率/声道的常驻 mpv 进程，
      短句之间不再反复启停进程，避免长间隔；
    - 空闲时由调用方（TTsCore）调 shutdown() 真正关闭常驻进程。
    """

    def __init__(self):
        self._proc = None
        self._sr = None
        self._channels = None
        self._lock = threading.Lock()

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

    def _close_locked(self):
        """硬关闭并清空当前 mpv 进程（打断用，调用方需持有锁）"""
        proc = self._proc
        self._proc = None
        self._sr = None
        self._channels = None
        if proc is not None:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def _graceful_close_locked(self):
        """优雅关闭：关闭 stdin 让 mpv 播完剩余缓冲后自然退出（调用方需持有锁）"""
        proc = self._proc
        self._proc = None
        self._sr = None
        self._channels = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        if proc.poll() is None:
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass

    def play_file(self, file_path: str, volume: float = 1.0) -> bool:
        """阻塞播放音频文件，返回 True 表示自然播完，False 表示被打断/失败"""
        if not self._exists() or not os.path.exists(file_path):
            return False
        cmd = self._base_cmd() + [f"--volume={int(volume * 100)}", os.path.abspath(file_path)]
        with self._lock:
            self._close_locked()
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"启动 mpv 失败: {e}")
                return False
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
            self._close_locked()
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
        _set_playing(True)
        return True

    def write(self, data: bytes, volume: float = 1.0) -> bool:
        """向 mpv stdin 写入 PCM 字节，返回 False 表示已停止/失败"""
        if not data:
            return True
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return False
        # 音量调节（int16 缩放）
        if volume != 1.0:
            try:
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                arr = (arr * volume).clip(-32768, 32767).astype(np.int16)
                data = arr.tobytes()
            except Exception:
                pass
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            # 被 stop 打断时 mpv 进程已终止，写入失败视为正常停止
            return False

    def close_stream(self):
        """软关闭：保留常驻 mpv 进程，供下个短句复用（不真正退出）"""
        pass

    def shutdown(self):
        """正常关闭常驻 mpv 进程：拖延 0.5 秒再播完剩余缓冲后退出（空闲时调用）"""
        with self._lock:
            if self._proc is None:
                return
        # 拖延 0.5 秒，让 mpv 边读边播、多消费 stdin 数据后再收尾
        time.sleep(0.5)
        with self._lock:
            had = self._proc is not None
            self._graceful_close_locked()
        if had:
            _set_playing(False)

    def stop(self):
        """立即停止当前播放并退出常驻进程"""
        with self._lock:
            had = self._proc is not None and self._proc.poll() is None
            self._close_locked()
        # 仅在确实停掉了本实例的进程时同步停止嘴部/身体表现，
        # 避免多播放器实例下误停其它实例正在播放的嘴部动画
        if had:
            _set_playing(False)

    def is_playing(self) -> bool:
        """返回当前是否有音频正在播放"""
        with self._lock:
            proc = self._proc
        return proc is not None and proc.poll() is None
