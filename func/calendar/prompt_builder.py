# -*- coding: utf-8 -*-
# func/calendar/prompt_builder.py
# 日期提示词构建：汇总节日/节气/生日为 markdown

from func.log.default_log import DefaultLog
from func.calendar.holiday import DateHoliday
from func.calendar.birthday import DateBirthday


class DatePromptBuilder:
    """日期提示词构建类：按顺序汇总节日、节气与生日为 markdown"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.holiday = DateHoliday()
        self.birthday = DateBirthday()

    def build(self, username=None) -> str:
        """构建当天日期提示词（无节日/节气/生日时返回空，标题为「今天是」）"""
        if not username:
            try:
                from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
                username = MeowLLMLtMemBridge().last_username
            except Exception:
                username = None
        lines = list(self.holiday.get_lines())
        if username and username in self.birthday.get_today_names():
            lines.append(f"{username}的生日")
        if not lines:
            return ""
        return "\n".join(["# 今天是"] + [f"- {line}" for line in lines])

    def build_no_user(self) -> str:
        """构建当天日期提示词（仅节日/节气，不获取 username、不检查生日）"""
        lines = list(self.holiday.get_lines())
        if not lines:
            return ""
        return "\n".join(["# 今天是"] + [f"- {line}" for line in lines])
