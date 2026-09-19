# -*- coding: utf-8 -*-
# func/audio/sources/microphone.py
# 麦克风输入采集（pyaudio）

import pyaudio

from func.audio.resample import StreamResampler
from func.audio.sources.base import BaseAudioSource


class MicrophoneSource(BaseAudioSource):
    """麦克风设备：打开、读取、流式重采样到 16k 单声道"""

    # 重采样输出持续不足时的最大补喂次数
    MAX_FEED_TRIES = 16

    def __init__(self, config, log, device_index=None):
        super().__init__(config, log)
        self._device_index = getattr(config, 'device_index', -1) if device_index is None else int(device_index)
        self._pyaudio = None
        self._stream = None
        self._device_rate = config.rate
        self._read_chunk = config.chunk
        self._passthrough = True
        self._resampler = None

    @staticmethod
    def list_devices():
        """枚举可用麦克风输入设备"""
        devices = []
        try:
            pa = pyaudio.PyAudio()
            try:
                count = pa.get_device_count()
                for i in range(count):
                    info = pa.get_device_info_by_index(i)
                    if int(info.get('maxInputChannels', 0)) <= 0:
                        continue
                    devices.append({
                        'index': i,
                        'name': info.get('name', ''),
                        'channels': int(info.get('maxInputChannels', 0)),
                        'rate': int(info.get('defaultSampleRate', 0)),
                        'kind': 'mic',
                    })
            finally:
                pa.terminate()
        except Exception:
            pass
        return devices

    def open(self):
        self._pyaudio = pyaudio.PyAudio()

        if self._device_index >= 0:
            device_info = self._pyaudio.get_device_info_by_index(self._device_index)
        else:
            device_info = self._pyaudio.get_default_input_device_info()

        self._device_rate = int(device_info.get('defaultSampleRate', self.config.rate))
        device_index = None if self._device_index < 0 else self._device_index

        self._stream = None
        if self.config.prefer_native_rate:
            self._stream = self._try_open(self.config.rate, device_index)
            if self._stream is not None:
                self._device_rate = self.config.rate

        self._read_chunk = self._chunk_for(self._device_rate)
        if self._stream is None:
            self._stream = self._open(self._device_rate, self._read_chunk, device_index)

        self._resampler = StreamResampler(
            self._device_rate, self.config.rate, self.config.chunk,
            in_channels=self.config.channels, log=self.log,
            converter=self.config.resample_converter,
        )
        self._passthrough = (self._device_rate == self.config.rate and self.config.channels == 1)
        if not self._passthrough and not self._resampler.available:
            self.log.error("重采样不可用且设备采样率不等于目标采样率，音频时序将不准确")
        self.log.info(f"🎤 麦克风设备: {device_info.get('name')}, 采样率: {self._device_rate}Hz")
        self.log.info(f"   目标分块: {self.config.chunk} samples ({self.config.chunk_size_ms}ms), "
                      f"读取块: {self._read_chunk} samples, 重采样: {'否' if self._passthrough else self.config.resample_converter}")

    def _chunk_for(self, device_rate: int) -> int:
        """按设备采样率换算每次读取的输入帧数（与输出帧等时）"""
        if device_rate == self.config.rate:
            return self.config.chunk
        return max(1, int(round(self.config.chunk * device_rate / self.config.rate)))

    def _try_open(self, rate: int, device_index):
        """尝试以指定采样率打开设备，失败返回 None"""
        try:
            return self._open(rate, self._chunk_for(rate), device_index)
        except Exception as e:
            self.log.warning(f"以 {rate}Hz 直接打开麦克风失败，回退设备默认采样率: {e}")
            return None

    def _open(self, rate: int, frames_per_buffer: int, device_index):
        """按指定参数打开 pyaudio 输入流"""
        return self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.config.channels,
            rate=rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=frames_per_buffer,
        )

    def read(self):
        if self._stream is None:
            return None
        if self._passthrough:
            return self._read_raw(self.config.chunk)
        tries = 0
        while True:
            frame = self._resampler.read_frame()
            if frame is not None:
                return frame
            tries += 1
            if tries > self.MAX_FEED_TRIES:
                self.log.warning("重采样输出持续不足，返回静音帧占位")
                return b'\x00' * (self.config.chunk * 2)
            raw = self._read_raw(self._read_chunk)
            if raw is None:
                return None
            self._resampler.feed(raw)

    def _read_raw(self, frames: int):
        """读取原始帧，异常返回 None"""
        try:
            return self._stream.read(frames, exception_on_overflow=False)
        except Exception as e:
            self.log.error(f"麦克风读取错误: {e}")
            return None

    def clear(self):
        """清空重采样缓冲（丢弃在途残块）"""
        if self._resampler is not None:
            self._resampler.reset()

    def close(self):
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pyaudio is not None:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None
