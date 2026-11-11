# -*- coding: utf-8 -*-
"""睡前监听状态：plugins/pc_power/state.json 的读写与状态迁移。

phase:
    idle      没在监听
    listening 监听中（到点执行关机）
    confirm   到点发现还有下载/上传，等主人确认
    off       已执行（进程随后被系统结束）
"""

import json
import os
import threading
import time

IDLE = "idle"
LISTENING = "listening"
CONFIRM = "confirm"
OFF = "off"

_PHASES = (IDLE, LISTENING, CONFIRM, OFF)


def _now_text(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return ""


class StateStore:
    """state.json 读写（原子写）；所有迁移都在锁内完成。"""

    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()

    # ==================== 基础读写 ====================
    @staticmethod
    def blank():
        return {
            "phase": IDLE,
            "trigger": "",
            "triggered_at": 0.0,
            "deadline": 0.0,
            "window_sec": 0,
            "resets": 0,
            "last_reset_at": 0.0,
            "cancel_reason": "",
            "off_reason": "",
            "transfers": [],
            "goodnight_count": 0,
            "goodnight_at": 0.0,
            "updated_at": "",
            "updated_ts": 0.0,
        }

    def _read_unlocked(self):
        try:
            if not os.path.isfile(self.path):
                return self.blank()
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return self.blank()
            out = self.blank()
            out.update(data)
            if out.get("phase") not in _PHASES:
                out["phase"] = IDLE
            return out
        except Exception:
            return self.blank()

    def _write_unlocked(self, data):
        ts = time.time()
        data["updated_ts"] = ts
        data["updated_at"] = _now_text(ts)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        return data

    def read(self):
        with self._lock:
            return self._read_unlocked()

    def write(self, data):
        with self._lock:
            return self._write_unlocked(dict(data or {}))

    # ==================== 迁移 ====================
    def begin(self, trigger, window_sec, now=None, note=""):
        """开始监听：重写 deadline"""
        now = float(now if now is not None else time.time())
        window = max(1.0, float(window_sec))
        with self._lock:
            data = self._read_unlocked()
            data.update({
                "phase": LISTENING,
                "trigger": str(trigger or ""),
                "triggered_at": now,
                "deadline": now + window,
                "window_sec": window,
                "resets": 0,
                "last_reset_at": now,
                "cancel_reason": "",
                "off_reason": "",
                "transfers": [],
                "note": str(note or ""),
            })
            return self._write_unlocked(data)

    def touch(self, now=None):
        """重置监听计时（只对 listening / confirm 生效）"""
        now = float(now if now is not None else time.time())
        with self._lock:
            data = self._read_unlocked()
            if data.get("phase") not in (LISTENING, CONFIRM):
                return data
            window = max(1.0, float(data.get("window_sec") or 1.0))
            data["deadline"] = now + window
            data["last_reset_at"] = now
            data["resets"] = int(data.get("resets") or 0) + 1
            return self._write_unlocked(data)

    def to_confirm(self, reason, transfers, window_sec, now=None):
        """有下载/上传在跑：转入确认态，等待主人明确回复"""
        now = float(now if now is not None else time.time())
        window = max(1.0, float(window_sec))
        with self._lock:
            data = self._read_unlocked()
            data.update({
                "phase": CONFIRM,
                "confirm_reason": str(reason or ""),
                "transfers": list(transfers or []),
                "window_sec": window,
                "deadline": now + window,
                "last_reset_at": now,
            })
            return self._write_unlocked(data)

    def cancel(self, reason, now=None):
        """取消监听/关机，回到 idle"""
        now = float(now if now is not None else time.time())
        with self._lock:
            data = self._read_unlocked()
            data.update({
                "phase": IDLE,
                "cancel_reason": str(reason or ""),
                "cancel_at": now,
                "deadline": 0.0,
                "transfers": [],
            })
            return self._write_unlocked(data)

    def mark_off(self, reason, now=None):
        """已执行关机（进程随后被系统结束，供下次启动判断残留）"""
        now = float(now if now is not None else time.time())
        with self._lock:
            data = self._read_unlocked()
            data.update({
                "phase": OFF,
                "off_reason": str(reason or ""),
                "off_at": now,
                "deadline": 0.0,
            })
            return self._write_unlocked(data)

    def note_goodnight(self, gap_sec=1800, now=None):
        """记一次晚安/要睡：间隔超过 gap 视为新一轮"""
        now = float(now if now is not None else time.time())
        gap = max(1.0, float(gap_sec))
        with self._lock:
            data = self._read_unlocked()
            last = float(data.get("goodnight_at") or 0)
            count = int(data.get("goodnight_count") or 0)
            count = count + 1 if last and (now - last) <= gap else 1
            data["goodnight_count"] = count
            data["goodnight_at"] = now
            return self._write_unlocked(data)

    def reset_stale(self):
        """进程重启：监听/确认/已关机 与晚安计数一律清零，绝不带病关机"""
        with self._lock:
            data = self._read_unlocked()
            old = str(data.get("phase") or "")
            active = old in (LISTENING, CONFIRM, OFF)
            data.update({
                "phase": IDLE,
                "trigger": "",
                "triggered_at": 0.0,
                "deadline": 0.0,
                "window_sec": 0,
                "resets": 0,
                "last_reset_at": 0.0,
                "cancel_reason": ("app_restart:" + old) if active else "",
                "off_reason": "",
                "confirm_reason": "",
                "transfers": [],
                "goodnight_count": 0,
                "goodnight_at": 0.0,
                "note": "",
                "boot_reset_at": time.time(),
            })
            return self._write_unlocked(data)
