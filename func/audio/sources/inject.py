# -*- coding: utf-8 -*-
# func/audio/sources/inject.py
# 接口注入源：外部 /audio/send 灌入 PCM，切成固定帧输出

import threading
from collections import deque

from func.audio.sources.base import BaseAudioSource


class InjectSource(BaseAudioSource):
    """外部接口注入的音频源（16k 单声道 int16 PCM），无物理设备。

    外部通过 inject(data) 灌入任意长度 PCM，内部切成 chunk 大小的帧，
    由会话采集循环按帧读取；末尾不足一帧的数据补零成一帧。
    """

    def __init__(self, config, log):
        super().__init__(config, log)
        self._lock = threading.Lock()
        self._pending = bytearray()
        self._queue = deque(maxlen=512)
        self._frame_bytes = config.chunk * 2

    @staticmethod
    def list_devices():
        return []

    def open(self):
        pass

    def close(self):
        with self._lock:
            self._pending.clear()
            self._queue.clear()

    def inject(self, data: bytes):
        """灌入一段 PCM，切成固定帧入队"""
        if not data:
            return
        with self._lock:
            self._pending.extend(data)
            while len(self._pending) >= self._frame_bytes:
                self._queue.append(bytes(self._pending[:self._frame_bytes]))
                del self._pending[:self._frame_bytes]

    def read(self):
        """取一帧；无完整帧时，若有剩余数据则补零成一帧，否则返回 None"""
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            if len(self._pending) > 0:
                frame = bytes(self._pending) + b'\x00' * (self._frame_bytes - len(self._pending))
                self._pending.clear()
                return frame
            return None
