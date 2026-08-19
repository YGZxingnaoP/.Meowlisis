# -*- coding: utf-8 -*-
# func/toolbox/napcat/emotion_bridge.py
# NapCat 在线情绪桥接：读写 .temp/latest_emotion_online.json（与主链路情绪隔离）

import os
import json

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class TBNapCatEmotionBridge:
    """NapCat → Emotion 在线情绪桥接：内存持有 online 情绪，重启后从落盘文件恢复"""

    LATEST_PATH = os.path.join(".temp", "latest_emotion_online.json")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._emotion = "happy"
        self._load()

    def set_emotion(self, emotion: str):
        """写入当前在线情绪"""
        self._emotion = str(emotion or "happy")
        self.log.info(f"NapCat 在线情绪指令: {self._emotion}")

    def get_emotion(self) -> str:
        """读取当前在线情绪"""
        return self._emotion

    def _load(self):
        """从落盘文件恢复上次在线情绪"""
        try:
            if os.path.exists(self.LATEST_PATH):
                with open(self.LATEST_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("emotion"):
                    self._emotion = str(data["emotion"])
        except Exception:
            pass
