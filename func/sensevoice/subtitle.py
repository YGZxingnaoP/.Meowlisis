# -*- coding: utf-8 -*-
# func/sensevoice/subtitle.py - 手机语音识别文本（用户字幕）环形缓冲
# 供手机端轮询显示"你说：..."，与 tts 的回复字幕（ReplyTextList）分开

import threading
from collections import deque


class SenseVoiceSubtitle:
    """用户识别字幕缓冲：识别到的话入队，手机端轮询取走显示"""

    def __init__(self, maxlen: int = 30):
        self._items = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def put(self, username: str, text: str):
        """写入一条用户识别字幕（识别线程调用）"""
        item = {"role": "user", "username": str(username or "手机用户"),
                "text": str(text or "")}
        with self._lock:
            self._items.append(item)

    def poll(self):
        """取走最早一条字幕；空返回 None（手机轮询调用）"""
        with self._lock:
            if not self._items:
                return None
            return self._items.popleft()

    def clear(self):
        """清空缓冲"""
        with self._lock:
            self._items.clear()
