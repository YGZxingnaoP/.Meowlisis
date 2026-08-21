# func/tts/player.py
# 音频播放器：soundfile 解码 + pyaudio 流式播放，替代 mpv 子进程
import os
import threading

import pyaudio
import soundfile as sf


class AudioPlayer:
    """库内流式音频播放器，支持立即打断"""

    CHUNK = 1024  # 每次写入的音频帧数

    def __init__(self):
        # 初始化 PortAudio 实例（失败时置空，播放时降级处理）
        try:
            self._pa = pyaudio.PyAudio()
        except Exception as e:
            self._pa = None
            print(f"初始化音频播放器失败: {e}")
        self._stream = None
        self._lock = threading.Lock()
        self._stop_flag = threading.Event()

    def play_file(self, file_path: str, volume: float = 1.0) -> bool:
        """阻塞播放音频文件，返回 True 表示自然播完，False 表示被打断"""
        # 播放器不可用或文件不存在时直接返回
        if self._pa is None or not os.path.exists(file_path):
            return False
        try:
            data, samplerate = sf.read(file_path, dtype="int16")
        except Exception as e:
            print(f"读取音频失败: {file_path} - {e}")
            return False
        if data is None or data.size == 0:
            return False

        # 单声道/双声道统一处理
        channels = 1 if data.ndim == 1 else data.shape[1]
        # 音量调节（float 数组缩放后转回 int16）
        if volume != 1.0:
            data = (data * volume).astype("int16")
        raw = data.tobytes()
        frame_bytes = self.CHUNK * channels * 2  # int16 每帧 2 字节

        # 开始新播放：清除旧的停止标志（新播放任务应能正常开始）
        self._stop_flag.clear()
        with self._lock:
            try:
                stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=channels,
                    rate=int(samplerate),
                    output=True,
                )
            except Exception as e:
                print(f"打开音频流失败: {e}")
                return False
            self._stream = stream

        try:
            # 分块写入，期间响应打断
            for i in range(0, len(raw), frame_bytes):
                if self._stop_flag.is_set():
                    return False
                chunk = raw[i:i + frame_bytes]
                if chunk:
                    stream.write(chunk)
            return True
        except Exception:
            # 被 stop 打断时 write 会抛异常，视为正常打断
            if self._stop_flag.is_set():
                return False
            raise
        finally:
            with self._lock:
                try:
                    stream.stop_stream()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
                self._stream = None

    def stop(self):
        """立即停止当前播放"""
        self._stop_flag.set()
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop_stream()
                except Exception:
                    pass

    def is_playing(self) -> bool:
        """返回当前是否有音频正在播放"""
        with self._lock:
            return self._stream is not None
