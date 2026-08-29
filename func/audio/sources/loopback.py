# -*- coding: utf-8 -*-
# func/audio/sources/loopback.py
# 电脑扬声器回环采集（WASAPI loopback，需 pyaudiowpatch）

from collections import deque

import numpy as np

from func.audio.sources.base import BaseAudioSource


class LoopbackSource(BaseAudioSource):
    """采集电脑扬声器输出（loopback），重采样到 16k 单声道"""

    def __init__(self, config, log, device_index=None):
        super().__init__(config, log)
        self._device_index = getattr(config, 'device_index', -1) if device_index is None else int(device_index)
        self._pyaudio = None
        self._stream = None
        self._device_rate = config.rate
        self._device_channels = config.channels
        self._need_resample = False
        self._need_downmix = False
        self._resample_buffer = bytearray()
        self._output_buffer = deque()
        self._read_chunk = config.chunk
        self._max_resample_buffer = 512 * 1024

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
        self._need_resample = (self._device_rate != self.config.rate)
        self._need_downmix = (self._device_channels > 1)

        if self._need_resample:
            try:
                import samplerate
                self._resampler = samplerate
            except ImportError:
                self.log.error("需要重采样但未安装 samplerate 库，请运行: pip install samplerate")
                self._need_resample = False

        self._read_chunk = self.config.chunk
        if self._need_resample:
            self._read_chunk = int(self.config.chunk * self._device_rate / self.config.rate)

        self._stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=self._device_channels,
            rate=self._device_rate,
            input=True,
            input_device_index=int(device.get('index')),
            frames_per_buffer=self._read_chunk,
        )

        self._resample_buffer.clear()
        self._output_buffer.clear()

        self.log.info(f"🔊 扬声器回环设备: {device.get('name')}, "
                      f"采样率: {self._device_rate}Hz, 声道: {self._device_channels}")

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
        if self._output_buffer:
            return self._output_buffer.popleft()

        while True:
            try:
                raw = self._stream.read(self._read_chunk, exception_on_overflow=False)
            except Exception as e:
                self.log.error(f"扬声器读取错误: {e}")
                return None

            if not self._need_resample and not self._need_downmix:
                return raw

            self._resample_buffer.extend(raw)
            self._process()
            if self._output_buffer:
                return self._output_buffer.popleft()

    def _process(self):
        # 每帧原始字节数（含多声道）
        frame_bytes = self._read_chunk * self._device_channels * 2
        while len(self._resample_buffer) >= frame_bytes:
            raw = self._resample_buffer[:frame_bytes]
            del self._resample_buffer[:frame_bytes]

            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

            # 多声道降混为单声道（取平均）
            if self._need_downmix:
                audio = audio.reshape(-1, self._device_channels).mean(axis=1)

            if self._need_resample:
                audio = self._resampler.resample(
                    audio,
                    self.config.rate / self._device_rate,
                    converter_type='sinc_fastest',
                )

            if len(audio) > self.config.chunk:
                audio = audio[:self.config.chunk]
            elif len(audio) < self.config.chunk:
                audio = np.pad(audio, (0, self.config.chunk - len(audio)))

            out = np.clip(audio * 32768, -32768, 32767).astype(np.int16)
            self._output_buffer.append(out.tobytes())

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
