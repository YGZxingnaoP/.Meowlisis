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

    def clear(self):
        """清空未消费的注入数据（按住说话结束时丢弃在途残块）"""
        with self._lock:
            self._pending.clear()
            self._queue.clear()

    def seal(self):
        """收句封装：把不足一帧的尾残补零成整帧，连同队列里未消费的帧一起取出。

        与中途补零不同，这里补的是**流末尾**：只增加一小段尾部静音，
        不会稀释语音；丢掉尾残才会让句尾最后一个字永久消失。
        """
        frame_bytes = self._frame_bytes
        with self._lock:
            frames = list(self._queue)
            self._queue.clear()
            if self._pending:
                data = bytes(self._pending)
                self._pending.clear()
                if len(data) < frame_bytes:
                    data += b'\x00' * (frame_bytes - len(data))
                frames.append(data[:frame_bytes])
            return frames

    def read(self):
        """取一帧；不够一帧就继续累积（不补零稀释语音），等凑满整帧再出；
        收句时的尾残由 seal() 补零成整帧取出，不再丢弃。"""
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None
