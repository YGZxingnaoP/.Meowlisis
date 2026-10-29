# -*- coding: utf-8 -*-
# func/toolbox/napcat/director/store.py
# QQ 导演状态存储：.temp/latest_director_qq.json，按 session 分开
# session 约定：qq_private:{user_id} / qq_group:{group_id}

import os
import copy
import json
import threading
import datetime

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class QQDirectorStore:
    """QQ 导演状态（本模块自包含，不经过主链路桥接）"""

    PATH = os.path.join(".temp", "latest_director_qq.json")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.RLock()
        self._data = None

    # ==================== 对外 ====================
    def get(self, session: str) -> dict:
        """读取某个 session 的计划（没有返回空 dict）"""
        key = str(session or "")
        with self._lock:
            data = self._load()
            plan = data.get(key)
            return copy.deepcopy(plan) if isinstance(plan, dict) else {}

    def set(self, session: str, plan: dict):
        """写入某个 session 的计划并落盘"""
        key = str(session or "")
        if not key or not isinstance(plan, dict):
            return
        with self._lock:
            data = self._load()
            data[key] = copy.deepcopy(plan)
            self._save(data)

    def clear(self, session: str, reason: str = "") -> dict:
        """结束某个 session 的走向（保留内容备查）"""
        key = str(session or "")
        with self._lock:
            data = self._load()
            plan = data.get(key)
            if not isinstance(plan, dict):
                return {}
            plan = dict(plan)
            plan["active"] = False
            plan["clear_reason"] = str(reason or "")
            plan["updated_at"] = self._now()
            data[key] = plan
            self._save(data)
            return dict(plan)

    # ==================== 内部 ====================
    @staticmethod
    def _now() -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _load(self) -> dict:
        if self._data is not None:
            return self._data
        data = {}
        try:
            if os.path.exists(self.PATH):
                with open(self.PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
        except Exception:
            self.log.exception("[QQ导演] 读取状态失败")
            data = {}
        self._data = data
        return self._data

    def _save(self, data: dict):
        try:
            os.makedirs(os.path.dirname(self.PATH), exist_ok=True)
            tmp = self.PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.PATH)
        except Exception:
            self.log.exception("[QQ导演] 写入状态失败")
