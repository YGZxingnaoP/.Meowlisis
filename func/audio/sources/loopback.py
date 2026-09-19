# -*- coding: utf-8 -*-
# func/audio/sources/loopback.py
# 电脑扬声器回环采集（WASAPI loopback，需 pyaudiowpatch）

from func.audio.resample import StreamResampler
from func.audio.sources.base import BaseAudioSource


class LoopbackSource(BaseAudioSource):
    """采集电脑扬声器输出（loopback），流式降混并重采样到 16k 单声道"""

    # 重采样输出持续不足时的最大补喂次数
    MAX_FEED_TRIES = 16

    def __init__(self, config, log, device_index=None):
        super().__init__(config, log)
        self._device_index = getattr(config, 'device_index', -1) if device_index is None else int(device_index)
        self._pyaudio = None
        self._stream = None
        self._device_rate = config.rate
        self._device_channels = config.channels
        self._read_chunk = config.chunk
        self._passthrough = True
        self._resampler = None

    @staticmethod
    def list_devices():
        """枚举可用的 WASAPI loopback（扬声器）设备"""
        devices = []
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            return devices
        try:
            pa = pyaudio.PyAudio()
            try:
                for info in pa.get_loopback_device_info_generator():
                    devices.append({
                        'index': int(info.get('index', 0)),
                        'name': info.get('name', ''),
                        'channels': int(info.get('maxInputChannels', 0)),
                        'rate': int(info.get('defaultSampleRate', 0)),
                        'kind': 'loopback',
                    })
            finally:
                pa.terminate()
        except Exception:
            pass
        return devices

    def open(self):
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            self.log.error("采集电脑扬声器需要 pyaudiowpatch，请运行: pip install pyaudiowpatch")
            raise RuntimeError("未安装 pyaudiowpatch，无法采集电脑扬声器")

        self._pyaudio = pyaudio.PyAudio()

        device = self._pick_device(self._pyaudio)
        self._device_rate = int(device.get('defaultSampleRate', self.config.rate))
        self._device_channels = int(device.get('maxInputChannels', self.config.channels))
        self._read_chunk = self._chunk_for(self._device_rate)

        self._stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=self._device_channels,
            rate=self._device_rate,
            input=True,
            input_device_index=int(device.get('index')),
            frames_per_buffer=self._read_chunk,
        )

        self._resampler = StreamResampler(
            self._device_rate, self.config.rate, self.config.chunk,
            in_channels=self._device_channels, log=self.log,
            converter=self.config.resample_converter,
        )
        self._passthrough = (self._device_rate == self.config.rate and self._device_channels == 1)
        if not self._passthrough and not self._resampler.available:
            self.log.error("重采样不可用且设备采样率不等于目标采样率，音频时序将不准确")

        self.log.info(f"🔊 扬声器回环设备: {device.get('name')}, "
                      f"采样率: {self._device_rate}Hz, 声道: {self._device_channels}, "
                      f"读取块: {self._read_chunk} samples, "
                      f"重采样: {'否' if self._passthrough else self.config.resample_converter}")

    def _chunk_for(self, device_rate: int) -> int:
        """按设备采样率换算每次读取的输入帧数（与输出帧等时）"""
        if device_rate == self.config.rate and self._device_channels == 1:
            return self.config.chunk
        return max(1, int(round(self.config.chunk * device_rate / self.config.rate)))

    def _pick_device(self, pa):
        """选择 loopback 设备：默认输出设备或按索引/名称匹配"""
        if self._device_index >= 0:
            try:
                return pa.get_device_info_by_index(self._device_index)
            except Exception:
                pass

        # paWASAPI 是模块级常量（数值 13），实例上取不到
        wasapi_const = 13
        try:
            import pyaudiowpatch as mod
            wasapi_const = getattr(mod, 'paWASAPI', 13)
        except Exception:
            pass

        try:
            wasapi_info = pa.get_host_api_info_by_type(wasapi_const)
            default = pa.get_device_info_by_index(wasapi_info['defaultOutputDevice'])
            for loopback in pa.get_loopback_device_info_generator():
                if default.get('name') and default['name'] in loopback.get('name', ''):
                    return loopback
            return default
        except Exception:
            for loopback in pa.get_loopback_device_info_generator():
                return loopback
            raise RuntimeError("未找到可用的扬声器回环设备")

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
            self.log.error(f"扬声器读取错误: {e}")
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
