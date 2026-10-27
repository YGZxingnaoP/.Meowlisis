# -*- coding: utf-8 -*-
# func/catpaws/state.py
# catpaws 链路状态（.temp/catpaws_state.json）：是否接管中、阶段、目标、会话与已读日志序号
import json
import os
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

CW_STATE_PATH = os.path.join(".temp", "catpaws_state.json")


@singleton
class CWCatPawsState:
    """链路状态管理（单例，线程安全，落盘 .temp/catpaws_state.json）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.RLock()
        self._data = self._load()

    @staticmethod
    def _default():
        return {"active": False, "phase": "idle", "goal": "", "meowid": "", "session": "",
                "seq": 0, "started_at": 0.0, "updated_at": 0.0, "reason": "", "run_id": 0}

    def _load(self):
        if not os.path.exists(CW_STATE_PATH):
            return self._default()
        try:
            with open(CW_STATE_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                base = self._default()
                for key in base:
                    if key not in data:
                        data[key] = base[key]
                return data
        except Exception:
            pass
        return self._default()

    def _save(self):
        try:
            directory = os.path.dirname(CW_STATE_PATH)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(CW_STATE_PATH, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("[CatPaws] 写入链路状态失败")

    def begin(self, goal, meowid="", session=""):
        with self._lock:
            now = time.time()
            self._data.update({"active": True, "phase": "control", "goal": str(goal or ""),
                               "meowid": str(meowid or ""), "session": str(session or ""),
                               "seq": 0, "started_at": now, "updated_at": now, "reason": "",
                               "run_id": now})
            self._save()
            return dict(self._data)

    def sync(self, phase="", session="", seq=None):
        with self._lock:
            changed = False
            if phase and self._data.get("phase") != str(phase):
                self._data["phase"] = str(phase)
                changed = True
            if session and self._data.get("session") != str(session):
                self._data["session"] = str(session)
                changed = True
            if seq is not None and int(self._data.get("seq") or 0) != int(seq):
                self._data["seq"] = int(seq)
                changed = True
            if not changed:
                return dict(self._data)
            self._data["updated_at"] = time.time()
            self._save()
            return dict(self._data)

    def finish(self, reason=""):
        with self._lock:
            self._data.update({"active": False, "phase": "end", "reason": str(reason or ""),
                               "updated_at": time.time()})
            self._save()
            return dict(self._data)

    def is_active(self):
        with self._lock:
            return bool(self._data.get("active"))

    def meowid(self):
        with self._lock:
            return str(self._data.get("meowid") or "")

    def seq(self):
        with self._lock:
            return int(self._data.get("seq") or 0)

    def snapshot(self):
        with self._lock:
            return dict(self._data)
