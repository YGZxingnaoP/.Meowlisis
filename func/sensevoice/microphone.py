# -*- coding: utf-8 -*-
# func/sensevoice/microphone.py
# 麦克风硬件采集与采样率转换

from collections import deque

import pyaudio
import numpy as np


class Microphone:
    """负责麦克风设备打开、读取、重采样与开关状态"""

    def __init__(self, config, log):
        self.config = config
        self.log = log
        self._pyaudio = None
        self._stream = None
        self._enabled = True
        self._device_rate = config.rate
        self._need_resample = False
        self._resampler = None
        self._resample_buffer = bytearray()
        self._output_buffer = deque()
        self._read_chunk = config.chunk
        self._max_resample_buffer = 512 * 1024

    def open(self):
        """打开默认输入设备并准备重采样"""
        self._pyaudio = pyaudio.PyAudio()
        device_info = self._pyaudio.get_default_input_device_info()
        self._device_rate = int(device_info['defaultSampleRate'])
        self._need_resample = (self._device_rate != self.config.rate)

        if self._need_resample:
            try:
                import samplerate
                self._resampler = samplerate
            except ImportError:
                self.log.error("需要重采样但未安装 samplerate 库，请运行: pip install samplerate")
                self.log.error("将尝试以目标采样率直接打开设备，若设备不支持可能导致错误")
                self._need_resample = False

        # 计算单次读取样本数（重采样时按设备采样率换算）
        self._read_chunk = self.config.chunk
        if self._need_resample:
            self._read_chunk = int(self.config.chunk * self._device_rate / self.config.rate)

        self._stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.config.channels,
            rate=self._device_rate,
            input=True,
            frames_per_buffer=self._read_chunk
        )

        self._resample_buffer.clear()
        self._output_buffer.clear()

        self.log.info(f"🎤 使用设备: {device_info['name']}, 设备采样率: {self._device_rate}Hz")
        self.log.info(f"   目标分块大小: {self.config.chunk} samples ({self.config.chunk_size_ms}ms)")

    def read(self):
        """读取并返回一帧重采样后的音频数据，出错时返回 None"""
        if self._output_buffer:
            return self._output_buffer.popleft()

        # 重采样时持续累积读取，直到产生一帧完整目标数据
        while True:
            try:
                raw = self._stream.read(self._read_chunk, exception_on_overflow=False)
            except Exception as e:
                self.log.error(f"音频读取错误: {e}")
                return None

            if not self._need_resample:
                return raw

            self._resample_buffer.extend(raw)
            self._resample()
            if self._output_buffer:
                return self._output_buffer.popleft()

    def _resample(self):
        """从输入缓冲中提取并重采样出完整目标帧"""
        needed_source_samples = int(self.config.chunk * self._device_rate / self.config.rate) + 5
        needed_bytes = needed_source_samples * 2

        # 防止缓冲无限增长，超限时丢弃一半
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
                converter_type='sinc_fastest'
            )

            # 补齐或截断到目标分块大小
            if len(resampled_float) > self.config.chunk:
                resampled_float = resampled_float[:self.config.chunk]
            elif len(resampled_float) < self.config.chunk:
                resampled_float = np.pad(
                    resampled_float,
                    (0, self.config.chunk - len(resampled_float))
                )

            resampled_int16 = np.clip(resampled_float * 32768, -32768, 32767).astype(np.int16)
            self._output_buffer.append(resampled_int16.tobytes())

    def close(self):
        """关闭流与设备并释放资源"""
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pyaudio is not None:
            self._pyaudio.terminate()
            self._pyaudio = None

    def set_enabled(self, enabled: bool):
        """设置麦克风开关状态，供前端实时切换"""
        self._enabled = enabled

    def is_enabled(self) -> bool:
        """返回麦克风当前开关状态"""
        return self._enabled
