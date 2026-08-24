# -*- coding: utf-8 -*-
# func/pipeline/llm_emotion.py
# LLM 与 Emotion 之间的情绪传递桥接

import os
import json

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class LLMEmotionBridge:
    """LLM → Emotion 情绪传递桥接：内存持有当前情绪与强度，重启后从落盘文件恢复

    - 提供订阅机制：情绪每次更新时通知订阅者（如 VTS 表情桥接）；
    - 订阅者在 pipeline 层注册，业务层（llm）不感知具体消费者，避免循环依赖。
    """

    LATEST_PATH = os.path.join(".temp", "latest_emotion.json")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._emotion = "happy"
        self._intensity = 3.0
        self._subscribers = []
        self._load()

    def set_emotion(self, emotion: str, intensity: float = 3.0):
        """写入当前情绪与强度，并通知订阅者（每更新一次触发一次表情操作）"""
        self._emotion = str(emotion or "happy")
        try:
            self._intensity = float(intensity)
        except Exception:
            self._intensity = 3.0
        self.log.info(f"情绪指令: {self._emotion} (intensity={self._intensity})")
        self._notify(self._emotion, self._intensity)

    def get_emotion(self) -> str:
        """读取当前情绪"""
        return self._emotion

    def get_intensity(self) -> float:
        """读取当前情绪强度"""
        return self._intensity

    def get_emotion_with_intensity(self) -> tuple:
        """读取当前情绪与强度"""
        return self._emotion, self._intensity

    # ==================== 订阅机制 ====================
    def subscribe(self, callback):
        """注册订阅者（callback(emotion, intensity)）"""
        if callback is not None and callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback):
        """移除订阅者"""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _notify(self, emotion: str, intensity: float):
        """通知所有订阅者（单个订阅者异常不影响其它）"""
        for cb in list(self._subscribers):
            try:
                cb(emotion, intensity)
            except Exception:
                self.log.exception("情绪订阅者回调异常")

    def _load(self):
        """从落盘文件恢复上次情绪与强度"""
        try:
            if os.path.exists(self.LATEST_PATH):
                with open(self.LATEST_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    if data.get("emotion"):
                        self._emotion = str(data["emotion"])
                    if "intensity" in data:
                        try:
                            self._intensity = float(data["intensity"])
                        except Exception:
                            pass
        except Exception:
            pass
