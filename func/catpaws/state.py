import json
import os
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

CW_STATE_PATH = os.path.join(".temp", "catpaws_state.json")


@singleton
class CWCatPawsState:
    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self):
        if not os.path.exists(CW_STATE_PATH):
            return self._default()
        try:
            with open(CW_STATE_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return self._merge(data)
        except Exception:
            pass
        return self._default()

    @staticmethod
    def _default():
        return {"active": False, "goal": "", "phase": "idle", "session": "",
                "started_at": 0, "updated_at": 0, "reason": "", "ok": False,
                "final": "", "last_answer": "", "source": ""}

    @staticmethod
    def _merge(data):
        base = CWCatPawsState._default()
        for key in base:
            if key not in data:
                data[key] = base[key]
        return data

    def _save(self):
        try:
            directory = os.path.dirname(CW_STATE_PATH)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(CW_STATE_PATH, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入 catpaws_state 失败")

    def begin(self, goal, session="", source=""):
        with self._lock:
            now = time.time()
            self._data.update({"active": True, "goal": str(goal or ""), "phase": "running",
                               "session": str(session or ""), "started_at": now,
                               "updated_at": now, "reason": "", "ok": False, "final": "",
                               "last_answer": "", "source": str(source or "")})
            self._save()
            return dict(self._data)

    def sync(self, phase, session=""):
        with self._lock:
            self._data["phase"] = str(phase or "idle")
            if session:
                self._data["session"] = str(session)
            self._data["updated_at"] = time.time()
            self._data["active"] = self._data["phase"] in ("running", "reflecting")
            self._save()
            return dict(self._data)

    def finish(self, reason="", ok=False, final=""):
        with self._lock:
            self._data.update({"active": False, "phase": "idle", "reason": str(reason or ""),
                               "ok": bool(ok), "final": str(final or ""),
                               "updated_at": time.time()})
            self._save()
            return dict(self._data)

    def set_answer(self, text):
        with self._lock:
            self._data["last_answer"] = str(text or "")
            self._data["updated_at"] = time.time()
            self._save()

    def is_active(self):
        with self._lock:
            return bool(self._data.get("active"))

    def snapshot(self):
        with self._lock:
            return dict(self._data)
