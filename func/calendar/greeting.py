# -*- coding: utf-8 -*-
# func/calendar/greeting.py
# 节日祝福文案：加载 greeting.json，按生日/节日/节气渲染祝福标题

import os
import json

from func.log.default_log import DefaultLog


class DateGreeting:
    """节日祝福文案加载与渲染（生日 / 节日 / 节气）

    greeting.json 结构：
    {
      "生日": "今天是{username}的生日，必须...",
      "节日": {"国庆节": "今天是国庆节，必须..."},
      "节气": {"立秋": "今天是立秋，必须..."}
    }
    未在 json 中单独配置的节日/节气，使用兜底模板。
    """

    # 兜底模板（{name} 节日/节气名，{username} 用户名）
    DEFAULT_BIRTHDAY = "今天是{username}的生日，必须给{username}送上生日祝福！"
    DEFAULT_HOLIDAY = "今天是{name}，必须给{username}送上节日祝福！"
    DEFAULT_SOLAR_TERM = "今天是{name}节气，必须给{username}送上节气问候！"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.path = os.path.join("func", "calendar", "greeting.json")
        self._data = None

    def _load(self) -> dict:
        if self._data is not None:
            return self._data
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            if not isinstance(self._data, dict):
                self._data = {}
        except Exception:
            self.log.exception("读取 greeting.json 失败")
            self._data = {}
        return self._data

    def is_solar_term(self, name: str) -> bool:
        """判断名称是否为节气（根据 json 的节气表）"""
        data = self._load()
        terms = data.get("节气") or {}
        return name in terms

    def render_birthday(self, username: str) -> str:
        data = self._load()
        tpl = str(data.get("生日") or self.DEFAULT_BIRTHDAY)
        return tpl.replace("{username}", username)

    def render_holiday(self, name: str, username: str) -> str:
        data = self._load()
        m = (data.get("节日") or {}).get(name)
        tpl = str(m or self.DEFAULT_HOLIDAY)
        return tpl.replace("{name}", name).replace("{username}", username)

    def render_solar_term(self, name: str, username: str) -> str:
        data = self._load()
        m = (data.get("节气") or {}).get(name)
        tpl = str(m or self.DEFAULT_SOLAR_TERM)
        return tpl.replace("{name}", name).replace("{username}", username)
