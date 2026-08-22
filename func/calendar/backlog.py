# -*- coding: utf-8 -*-
# func/calendar/backlog.py
# 待办提醒调度：读取 character/backlog/*.json，按计划时刻主动提醒

import os
import json
import random
import threading
import datetime
import re

from func.log.default_log import DefaultLog


class DateBacklog:
    """待办提醒类：独立线程轮询，按计划时刻触发提醒"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.backlog_dir = os.path.join("character", "backlog")
        self.state_path = os.path.join(".temp", "calendar_backlog_state.json")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._state = self._load_state()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.log.info("待办提醒线程已启动")

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.check()
            except Exception:
                self.log.exception("待办提醒检查异常")
            self._stop.wait(5)

    def check(self):
        now = datetime.datetime.now()
        today = now.strftime("%Y-%m-%d")
        items = self._load_backlogs()
        with self._lock:
            for k in list(self._state.keys()):
                if k != today:
                    self._state.pop(k, None)
            state = self._state.setdefault(today, {})

        for username, item in items:
            key = self._item_key(username, item)
            with self._lock:
                entry = state.get(key)
                if entry is None:
                    entry = {"planned": [], "fired": []}
                    state[key] = entry
                planned = [m for m in (self._parse_moment(s) for s in entry["planned"]) if m]
                if not planned:
                    planned = self._compute_moments(item, now)
                    entry["planned"] = [m.strftime("%Y-%m-%d %H:%M:%S") for m in planned]
            fired = entry.get("fired", [])
            for m in planned:
                m_str = m.strftime("%Y-%m-%d %H:%M:%S")
                if m_str in fired:
                    continue
                if now >= m:
                    with self._lock:
                        if m_str not in entry["fired"]:
                            entry["fired"].append(m_str)
                    self._fire(username, item, m)
        self._save_state()

    def _fire(self, username, item, moment):
        def _run():
            try:
                time_str = str(item.get("time") or "")
                content = str(item.get("content") or "")
                qq = self._to_bool(item.get("qq"))
                from func.pipeline.calendar_llm import DateCalendarLLM
                DateCalendarLLM().remind(username, time_str, content)
                if qq:
                    from func.pipeline.calendar_toolbox import DateCalendarToolbox
                    DateCalendarToolbox().remind(username, time_str, content)
            except Exception:
                self.log.exception("待办提醒触发异常")

        threading.Thread(target=_run, daemon=True).start()

    def _compute_moments(self, item, now):
        day = str(item.get("day") or "").strip()
        time_str = str(item.get("time") or "").strip()
        h, m = self._parse_time(time_str)
        if h is None:
            return []
        if day and day.lower() != "none":
            try:
                month, dday = [int(x) for x in day.split("-")]
            except Exception:
                return []
            if now.month != month or now.day != dday:
                return []
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        typ = str(item.get("type") or "instant").strip()
        if typ == "steady":
            loop = max(1, self._to_int(item.get("loop"), 1))
            interval = max(1, self._to_int(item.get("repeat_interval"), 300))
            first = target - datetime.timedelta(seconds=random.uniform(30, 300))
            return [first + datetime.timedelta(seconds=interval * k) for k in range(loop)]
        return [
            target - datetime.timedelta(minutes=5),
            target - datetime.timedelta(seconds=30),
        ]

    def _load_backlogs(self):
        result = []
        if not os.path.isdir(self.backlog_dir):
            return result
        for fname in os.listdir(self.backlog_dir):
            if not fname.endswith(".json"):
                continue
            data = self._load_json(os.path.join(self.backlog_dir, fname))
            if not isinstance(data, dict):
                continue
            username = str(data.get("username") or "").strip() or fname[:-5]
            todos = data.get("to_do_list")
            if isinstance(todos, list):
                for item in todos:
                    if isinstance(item, dict):
                        result.append((username, item))
        return result

    @staticmethod
    def _item_key(username, item):
        day = str(item.get("day") or "").strip()
        time_str = str(item.get("time") or "").strip()
        content = str(item.get("content") or "").strip()
        return f"{username}::{day}::{time_str}::{content}"

    @staticmethod
    def _parse_time(time_str):
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", time_str)
        if not m:
            return None, None
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
        return None, None

    @staticmethod
    def _parse_moment(s):
        try:
            return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    @staticmethod
    def _to_int(v, default):
        try:
            return int(v)
        except Exception:
            return default

    @staticmethod
    def _to_bool(v):
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    def _load_json(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            self.log.exception(f"读取待办文件失败: {path}")
            return None

    def _load_state(self):
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception("读取待办状态失败")
        return {}

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with self._lock:
                data = json.loads(json.dumps(self._state, ensure_ascii=False))
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入待办状态失败")
