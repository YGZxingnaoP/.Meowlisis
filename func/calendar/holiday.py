# -*- coding: utf-8 -*-
# func/calendar/holiday.py
# 节日获取：当天公历/农历日期、24节气、公历/农历/浮动节日

import os
import json
import datetime
from typing import List

from func.log.default_log import DefaultLog


class DateHoliday:
    """日期节日类：获取当天日期、农历日期与对应节日/节气"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.path = os.path.join("func", "calendar", "holiday.json")
        self._data = None

    def _load_data(self) -> dict:
        """读取 holiday.json 节日配置（缺失或损坏时返回空 dict）"""
        if self._data is not None:
            return self._data
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except Exception:
            self.log.exception("读取 holiday.json 失败")
            self._data = {}
        return self._data

    def get_today(self) -> datetime.date:
        """返回今天日期"""
        return datetime.date.today()

    def get_solar_text(self) -> str:
        """返回当天公历日期文本（如 10月1日）"""
        d = self.get_today()
        return f"{d.month}月{d.day}日"

    def get_lunar(self):
        """返回当天农历对象（lunar_python，未安装时返回 None）"""
        try:
            from lunar_python import Solar
            d = self.get_today()
            return Solar.fromYmd(d.year, d.month, d.day).getLunar()
        except Exception:
            self.log.exception("加载 lunar_python 失败")
            return None

    def get_lunar_text(self) -> str:
        """返回当天农历日期文本（如 八月廿三，无农历对象时返回空）"""
        lunar = self.get_lunar()
        if lunar is None:
            return ""
        return f"{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}"

    def get_lines(self) -> List[str]:
        """返回当天节日/节气行列表（如 ['国庆节 10月1日', '立秋 六月廿五']）"""
        lines = []
        data = self._load_data()
        d = self.get_today()
        solar_text = self.get_solar_text()

        # 公历固定节日
        solar_map = data.get("solar", {})
        key = f"{d.month}-{d.day}"
        if key in solar_map:
            lines.append(f"{solar_map[key]} {solar_text}")

        # 农历节气与农历节日
        lunar = self.get_lunar()
        if lunar is not None:
            lunar_text = self.get_lunar_text()
            jieqi = lunar.getJieQi()
            if jieqi:
                lines.append(f"{jieqi} {lunar_text}")
            lunar_map = data.get("lunar", {})
            lunar_key = f"{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}"
            if lunar_key in lunar_map:
                lines.append(f"{lunar_map[lunar_key]} {lunar_text}")
            # 除夕为农历腊月最后一天（日期不固定，用内置节日判断）
            if "除夕" in lunar.getFestivals():
                lines.append(f"除夕 {lunar_text}")

        # 浮动节日（母亲节、父亲节）
        for item in data.get("floating", []):
            if self._is_floating_today(d, item):
                lines.append(f"{item.get('name')} {solar_text}")

        return lines

    def _is_floating_today(self, d, item) -> bool:
        """判断今天是否为指定浮动节日（某月第 n 个指定星期）"""
        try:
            month = int(item.get("month"))
            week = int(item.get("week"))
            weekday = int(item.get("weekday", 6))
            if d.month != month:
                return False
            return d == self._nth_weekday(d.year, month, weekday, week)
        except Exception:
            return False

    @staticmethod
    def _nth_weekday(year, month, weekday, n) -> datetime.date:
        """计算某月第 n 个指定星期（0=周一...6=周日）的日期"""
        first = datetime.date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return datetime.date(year, month, 1 + offset + (n - 1) * 7)
