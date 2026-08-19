# -*- coding: utf-8 -*-
# func/calendar/birthday.py
# 生日提醒：遍历用户档案匹配当天生日

import os
import re
import json
import datetime
from typing import List, Dict

from func.log.default_log import DefaultLog


class DateBirthday:
    """日期生日类：遍历用户档案，匹配当天过生日的用户（同一天内结果缓存）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.info_dir = os.path.join("character", "info", "users_info")
        self._cache_date = None
        self._cache_names = []

    def get_today_names(self) -> List[str]:
        """返回今天过生日的用户名列表（按天缓存，仅当天首次调用时遍历档案）"""
        today = datetime.date.today()
        if self._cache_date != today:
            self._cache_date = today
            self._cache_names = self._scan_today_names()
        return self._cache_names

    def _scan_today_names(self) -> List[str]:
        """遍历用户档案，返回今天过生日的用户名列表"""
        today = datetime.date.today()
        names = []
        for name, (month, day) in self._collect_birthdays().items():
            if month == today.month and day == today.day:
                names.append(name)
        return names

    def _collect_birthdays(self) -> Dict[str, tuple]:
        """遍历 users_info 下所有 json，收集 {用户名: (月, 日)}，latest 文件优先覆盖"""
        result = {}
        if not os.path.isdir(self.info_dir):
            return result
        for fname in os.listdir(self.info_dir):
            if not fname.endswith(".json"):
                continue
            data = self._load(os.path.join(self.info_dir, fname))
            name = str(data.get("name", "") or "").strip()
            birthday = str(data.get("birthday", "") or "").strip()
            parsed = self._parse_birthday(birthday) if birthday else None
            if not name:
                continue
            if parsed and (name not in result or fname.endswith("_latest.json")):
                result[name] = parsed
        return result

    @staticmethod
    def _load(path: str) -> dict:
        """读取单个用户档案（缺失或损坏时返回空 dict）"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _parse_birthday(birthday: str):
        """解析公历生日文本（如 4月23日），返回 (月, 日) 或 None"""
        m = re.match(r'^\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?\s*$', birthday)
        if not m:
            return None
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return month, day
        return None
