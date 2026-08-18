# -*- coding: utf-8 -*-
# func/pipeline/llm_emotion.py
# LLM 与 Emotion 之间的情绪传递桥接

import os
import json

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class LLMEmotionBridge:
    """LLM → Emotion 情绪传递桥接：内存持有当前情绪，重启后从落盘文件恢复"""

    LATEST_PATH = os.path.join(".temp", "latest_emotion.json")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._emotion = "happy"
        self._load()

    def set_emotion(self, emotion: str):
        """写入当前情绪"""
        self._emotion = str(emotion or "happy")
        self.log.info(f"情绪指令: {self._emotion}")

    def get_emotion(self) -> str:
        """读取当前情绪"""
        return self._emotion

    def _load(self):
        """从落盘文件恢复上次情绪"""
        try:
            if os.path.exists(self.LATEST_PATH):
                with open(self.LATEST_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("emotion"):
                    self._emotion = str(data["emotion"])
        except Exception:
            pass
