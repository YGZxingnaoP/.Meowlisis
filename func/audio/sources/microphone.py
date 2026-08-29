# -*- coding: utf-8 -*-
# func/audio/sources/microphone.py
# 麦克风输入采集（pyaudio）

from collections import deque

import pyaudio
import numpy as np

from func.audio.sources.base import BaseAudioSource


class MicrophoneSource(BaseAudioSource):
    """麦克风设备：打开、读取、重采样到 16k 单声道"""

    def __init__(self, config, log, device_index=None):
        super().__init__(config, log)
        self._device_index = getattr(config, 'device_index', -1) if device_index is None else int(device_index)
        self._pyaudio = None
        self._stream = None
        self._device_rate = config.rate
        self._need_resample = False
        self._resample_buffer = bytearray()
        self._output_buffer = deque()
        self._read_chunk = config.chunk
        self._max_resample_buffer = 512 * 1024

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

        # 选择设备：默认输入设备或指定索引
        if self._device_index >= 0:
            device_info = self._pyaudio.get_device_info_by_index(self._device_index)
        else:
            device_info = self._pyaudio.get_default_input_device_info()

        self._device_rate = int(device_info.get('defaultSampleRate', self.config.rate))
        self._need_resample = (self._device_rate != self.config.rate)

        if self._need_resample:
            try:
                import samplerate
                self._resampler = samplerate
            except ImportError:
                self.log.error("需要重采样但未安装 samplerate 库，请运行: pip install samplerate")
                self.log.error("将尝试以目标采样率直接打开设备，若设备不支持可能导致错误")
                self._need_resample = False

        self._read_chunk = self.config.chunk
        if self._need_resample:
            self._read_chunk = int(self.config.chunk * self._device_rate / self.config.rate)

        device_index = None if self._device_index < 0 else self._device_index
        self._stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.config.channels,
            rate=self._device_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=self._read_chunk,
        )

        self._resample_buffer.clear()
        self._output_buffer.clear()

        self.log.info(f"🎤 麦克风设备: {device_info.get('name')}, 采样率: {self._device_rate}Hz")
        self.log.info(f"   目标分块: {self.config.chunk} samples ({self.config.chunk_size_ms}ms)")

    def read(self):
        if self._stream is None:
            return None
        if self._output_buffer:
            return self._output_buffer.popleft()

        while True:
            try:
                raw = self._stream.read(self._read_chunk, exception_on_overflow=False)
            except Exception as e:
                self.log.error(f"麦克风读取错误: {e}")
                return None

            if not self._need_resample:
                return raw

            self._resample_buffer.extend(raw)
            self._resample()
            if self._output_buffer:
                return self._output_buffer.popleft()

    def _resample(self):
        needed_source_samples = int(self.config.chunk * self._device_rate / self.config.rate) + 5
        needed_bytes = needed_source_samples * 2

        if len(self._resample_buffer) > self._max_resample_buffer:
            discard = len(self._resample_buffer) // 2
            del self._resample_buffer[:discard]

        while len(self._resample_buffer) >= needed_bytes:
            source_data = self._resample_buffer[:needed_bytes]
            del self._resample_buffer[:needed_bytes]

            audio_int16 = np.frombuffer(source_data, dtype=np.int16)
            audio_float = audio_int16.astype(np.float32) / 32768.0
            resampled_float = self._resampler.resample(
                audio_float,
                self.config.rate / self._device_rate,
                converter_type='sinc_fastest',
            )

            if len(resampled_float) > self.config.chunk:
                resampled_float = resampled_float[:self.config.chunk]
            elif len(resampled_float) < self.config.chunk:
                resampled_float = np.pad(
                    resampled_float,
                    (0, self.config.chunk - len(resampled_float)),
                )

            resampled_int16 = np.clip(resampled_float * 32768, -32768, 32767).astype(np.int16)
            self._output_buffer.append(resampled_int16.tobytes())

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
