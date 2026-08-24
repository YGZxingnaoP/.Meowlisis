# -*- coding: utf-8 -*-
# func/meowsinger/state.py
# meowsinger 运行时状态（.temp/song_state.json），供各模块检测唱歌/学歌/任务队列
import os
import json
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

STATE_PATH = os.path.join(".temp", "song_state.json")


@singleton
class MeowSingerState:
    """唱歌状态与任务队列管理（单例，线程安全，落盘 .temp/song_state.json）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self):
        if not os.path.exists(STATE_PATH):
            return self._default()
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return self._default()
            return self._merge_default(data)
        except Exception:
            return self._default()

    @staticmethod
    def _default():
        return {
            "singing": {"active": False, "mode": "", "song_title": ""},
            "learning": {"active": False},
            "rvc_queue": [],
            "pending_messages": [],
        }

    @staticmethod
    def _merge_default(data):
        base = MeowSingerState._default()
        for key in base:
            if key not in data:
                data[key] = base[key]
        return data

    def _save(self):
        try:
            os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入 song_state 失败")

    def is_singing(self):
        with self._lock:
            return bool(self._data.get("singing", {}).get("active"))

    def start_singing(self, mode, song_title=""):
        with self._lock:
            self._data["singing"] = {"active": True, "mode": mode, "song_title": song_title}
            self._save()

    def end_singing(self):
        with self._lock:
            self._data["singing"] = {"active": False, "mode": "", "song_title": ""}
            self._save()

    def set_learning(self, active):
        with self._lock:
            self._data["learning"] = {"active": bool(active)}
            self._save()

    def add_rvc_task(self, task):
        with self._lock:
            self._data.setdefault("rvc_queue", []).append(task)
            self._save()

    def pop_rvc_task(self):
        with self._lock:
            if not self._data.get("rvc_queue"):
                return None
            task = self._data["rvc_queue"].pop(0)
            self._save()
            return task

    def has_rvc_task(self):
        with self._lock:
            return bool(self._data.get("rvc_queue"))

    def add_pending_message(self, username, text, source):
        with self._lock:
            self._data.setdefault("pending_messages", []).append({
                "username": username,
                "text": text,
                "source": source,
                "time": time.strftime("%H:%M:%S"),
            })
            self._save()

    def take_pending_messages(self):
        with self._lock:
            items = list(self._data.get("pending_messages", []))
            self._data["pending_messages"] = []
            self._save()
            return items
