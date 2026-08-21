# -*- coding: utf-8 -*-
# func/calendar/prompt_builder.py
# 日期提示词构建：汇总节日/节气/生日为 markdown，并处理当天首次说话的节日祝福

from func.log.default_log import DefaultLog
from func.calendar.holiday import DateHoliday
from func.calendar.birthday import DateBirthday
from func.calendar.daily_user import DateDailyUser
from func.calendar.greeting import DateGreeting


class DatePromptBuilder:
    """日期提示词构建类：按顺序汇总节日、节气与生日为 markdown

    - 无节日/节气/生日时返回空；
    - 用户当天第一次说话且有节日/节气/生日时，标题改为祝福指令；
    - 祝福优先级：生日 > 节日 > 节气。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.holiday = DateHoliday()
        self.birthday = DateBirthday()
        self.daily_user = DateDailyUser()
        self.greeting = DateGreeting()

    def build(self, username=None) -> str:
        """构建当天日期提示词（无节日/节气/生日时返回空）"""
        if not username:
            try:
                from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
                username = MeowLLMLtMemBridge().last_username
            except Exception:
                username = None

        lines = list(self.holiday.get_lines())
        is_birthday = bool(username) and username in self.birthday.get_today_names()
        if is_birthday:
            lines.append(f"{username}的生日")

        # 第一次说话判断 + 记录（原子操作，username 为空不判定）
        is_first = False
        if username:
            is_first = self.daily_user.check_first_and_mark(username)

        if not lines:
            return ""

        title = "# 今天是"
        if is_first:
            greeting = self._greeting_title(username, lines, is_birthday)
            if greeting:
                title = f"# {greeting}"

        return "\n".join([title] + [f"- {line}" for line in lines])

    def build_no_user(self) -> str:
        """构建当天日期提示词（仅节日/节气，不获取 username、不检查生日、不判断首次说话）"""
        lines = list(self.holiday.get_lines())
        if not lines:
            return ""
        return "\n".join(["# 今天是"] + [f"- {line}" for line in lines])

    # ==================== 祝福标题 ====================
    def _greeting_title(self, username, lines, is_birthday: bool) -> str:
        """生成祝福标题文案（生日 > 节日 > 节气），无匹配返回空串"""
        # 生日优先
        if is_birthday:
            return self.greeting.render_birthday(username)

        # 从 lines 中区分节日与节气，节日优先
        holiday_name = None
        term_name = None
        for line in lines:
            parts = str(line).split()
            name = parts[0] if parts else ""
            if not name:
                continue
            if self.greeting.is_solar_term(name):
                if term_name is None:
                    term_name = name
            else:
                if holiday_name is None:
                    holiday_name = name

        if holiday_name:
            return self.greeting.render_holiday(holiday_name, username)
        if term_name:
            return self.greeting.render_solar_term(term_name, username)
        return ""
