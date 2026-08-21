# -*- coding: utf-8 -*-
# func/calendar/daily_user.py
# 当天说话人列表：判断用户是否当天第一次发消息，记录到 .temp/today_user_list.json
# 内存日期 + 文件持久化，跨天自动清空

import os
import json
import datetime
import threading
from typing import List

from func.log.default_log import DefaultLog


class DateDailyUser:
    """当天说话人管理。

    - 内存保存当天日期与用户列表；
    - 日期不匹配（跨天）时直接清空，重新开始；
    - 文件格式：{"date": "YYYY-MM-DD", "users": [...]}
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.path = os.path.join(".temp", "today_user_list.json")
        self._lock = threading.Lock()
        self._mem_date = None          # 内存日期
        self._mem_users: List[str] = []  # 内存用户列表
        self._loaded = False           # 当天是否已从文件加载

    @staticmethod
    def _today() -> str:
        return datetime.date.today().isoformat()

    def _ensure_today(self):
        """确保内存状态对应今天，跨天则清空"""
        today = self._today()
        if self._mem_date != today:
            self._mem_date = today
            self._mem_users = []
            self._loaded = False
        return today

    def is_first_time(self, username: str) -> bool:
        """判断用户是否当天第一次发消息（username 为空返回 False）"""
        username = (username or "").strip()
        if not username:
            return False
        with self._lock:
            self._ensure_today()
            if not self._loaded:
                self._load()
                self._loaded = True
            return username not in self._mem_users

    def mark_spoken(self, username: str):
        """记录用户当天说过话（去重 + 写文件）"""
        username = (username or "").strip()
        if not username:
            return
        with self._lock:
            self._ensure_today()
            if not self._loaded:
                self._load()
                self._loaded = True
            if username not in self._mem_users:
                self._mem_users.append(username)
                self._save()

    def check_first_and_mark(self, username: str) -> bool:
        """原子操作：判断是否当天第一次说话，并立即记录。

        在同一锁内完成「判断 + 记录」，避免并发下同一用户重复触发祝福。
        返回 True 表示当天第一次（已记录），False 表示之前已说过话。
        username 为空返回 False（不判定、不记录）。
        """
        username = (username or "").strip()
        if not username:
            return False
        with self._lock:
            self._ensure_today()
            if not self._loaded:
                self._load()
                self._loaded = True
            first = username not in self._mem_users
            if first:
                self._mem_users.append(username)
                self._save()
            return first

    def _load(self):
        """从文件加载当天用户列表；日期不匹配则清空"""
        try:
            if not os.path.exists(self.path):
                self._mem_users = []
                return
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("date") == self._mem_date:
                users = data.get("users") or []
                self._mem_users = [str(u) for u in users if u]
            else:
                self._mem_users = []
        except Exception:
            self.log.exception("读取 today_user_list.json 失败")
            self._mem_users = []

    def _save(self):
        """写回当天用户列表"""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            data = {"date": self._mem_date, "users": self._mem_users}
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入 today_user_list.json 失败")
