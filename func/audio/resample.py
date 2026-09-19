# -*- coding: utf-8 -*-
# func/audio/resample.py
# 流式重采样：跨块保持滤波状态，按目标帧长精确输出 16k 单声道 int16

import numpy as np


class StreamResampler:
    """流式重采样器：先降混单声道，再跨块连续重采样，按帧精确取用

    与逐块调用 samplerate.resample 不同，本类持有采样器内部状态，
    块与块之间滤波连续，不会在每个块边界产生瞬态；重采样输出经缓冲后
    按 out_chunk 精确切帧，既不截断也不补零，长期运行无采样漂移。
    """

    # 输出缓冲安全上限（按目标帧长的倍数控制）
    MAX_BUFFER_FRAMES = 32

    def __init__(self, in_rate: int, out_rate: int, out_chunk: int,
                 in_channels: int = 1, log=None, converter: str = 'sinc_medium'):
        self.in_rate = int(in_rate)
        self.out_rate = int(out_rate)
        self.out_chunk = int(out_chunk)
        self.in_channels = max(1, int(in_channels))
        self.log = log
        self.converter = converter or 'sinc_medium'
        self.ratio = self.out_rate / self.in_rate
        self.in_chunk = max(1, int(round(self.out_chunk * self.in_rate / self.out_rate)))
        self.in_chunk_bytes = self.in_chunk * self.in_channels * 2
        self._frame_bytes = self.out_chunk * 2
        self._out = bytearray()
        self._sampler = None
        if self.in_rate != self.out_rate:
            try:
                import samplerate
                self._sampler = samplerate.Resampler(self.converter, channels=1)
            except Exception:
                if self.log:
                    self.log.exception("流式重采样器初始化失败，将退回原生采样率读取")
                self._sampler = None

    @property
    def available(self) -> bool:
        """重采样能力是否可用（输入输出同速率时视为无需重采样）"""
        return self.in_rate == self.out_rate or self._sampler is not None

    @property
    def frame_bytes(self) -> int:
        """一帧输出的字节数（16k 单声道 int16）"""
        return self._frame_bytes

    def reset(self):
        """清空内部缓冲与采样器状态"""
        self._out.clear()
        if self._sampler is not None:
            try:
                self._sampler.reset()
            except Exception:
                pass

    def feed(self, raw: bytes):
        """喂入 in_chunk 帧原始 PCM，降混并重采样后累积到输出缓冲"""
        if not raw:
            return
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if self.in_channels > 1:
            usable = (len(audio) // self.in_channels) * self.in_channels
            if usable <= 0:
                return
            audio = audio[:usable].reshape(-1, self.in_channels).mean(axis=1)
        if self._sampler is not None:
            audio = self._sampler.process(audio, self.ratio)
        if audio is None or len(audio) == 0:
            return
        pcm = np.clip(audio * 32768.0, -32768, 32767).astype(np.int16)
        self._out.extend(pcm.tobytes())
        limit = self._frame_bytes * self.MAX_BUFFER_FRAMES
        if len(self._out) > limit:
            dropped = len(self._out) - limit
            if self.log:
                self.log.warning(f"重采样输出缓冲超限，丢弃最旧 {dropped} 字节")
            del self._out[:dropped]

    def read_frame(self):
        """取一帧（out_chunk 个 int16）；不足一帧返回 None"""
        if len(self._out) < self._frame_bytes:
            return None
        frame = bytes(self._out[:self._frame_bytes])
        del self._out[:self._frame_bytes]
        return frame
