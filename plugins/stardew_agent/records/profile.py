# -*- coding: utf-8 -*-
"""角色在星露谷里的运行时状态（按存档隔离）。

只放「现在」和「跨天需要记住的小状态」：心情、性格、最近一次日记/记忆/习惯
的日期、去过的地方、计数器、最近一句心声。不做长期记忆，长期记忆在 memory/。
"""

import json

from . import store as store_mod

VERSION = 1
DEFAULT_TRAITS = {
    "diligence": 0.6,
    "sociability": 0.5,
    "curiosity": 0.5,
    "thrift": 0.5,
}


def _default():
    return {
        "version": VERSION,
        "created": store_mod.now(),
        "updated": store_mod.now(),
        "traits": dict(DEFAULT_TRAITS),
        "mood": 0.0,
        "last_day": "",
        "last_diary_day": "",
        "last_memory_day": "",
        "last_habit_window": "",
        "last_plan_day": "",
        "last_share_at": 0,
        "thought": "",
        "activity": "闲着",
        "visited": {},
        "counters": {},
        "skills": {},
        "professions": [],
        "pending_profession": None,
        "stats": {},
    }


class Profile:
    def __init__(self, store):
        self.store = store
        self.data = self._load()

    def _load(self):
        data = self.store.load_json(self.store.profile_path(), _default())
        if not isinstance(data, dict):
            data = _default()
        for key, value in _default().items():
            data.setdefault(key, value)
        if not isinstance(data.get("traits"), dict):
            data["traits"] = dict(DEFAULT_TRAITS)
        for key, value in DEFAULT_TRAITS.items():
            data["traits"].setdefault(key, value)
        return data

    def save(self):
        self.data["version"] = VERSION
        self.data["updated"] = store_mod.now()
        self.store.save_json(self.store.profile_path(), self.data)
        return self.data

    # ---- 性格 / 心情 ----
    @property
    def traits(self):
        return dict(self.data.get("traits") or DEFAULT_TRAITS)

    def set_traits(self, traits):
        clean = dict(DEFAULT_TRAITS)
        for key, value in (traits or {}).items():
            try:
                clean[key] = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                continue
        self.data["traits"] = clean
        self.save()
        return clean

    @property
    def mood(self):
        try:
            return float(self.data.get("mood") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def add_mood(self, delta):
        value = max(-1.0, min(1.0, self.mood + float(delta or 0.0)))
        self.data["mood"] = round(value, 2)
        self.save()
        return value

    def mood_text(self):
        value = self.mood
        if value >= 0.6:
            return "心情很好"
        if value >= 0.2:
            return "挺有精神"
        if value >= -0.2:
            return "还算平静"
        if value >= -0.6:
            return "有点累"
        return "心情低落"

    # ---- 日期 ----
    def mark_day(self, day_stamp):
        if self.data.get("last_day") != day_stamp:
            self.data["last_day"] = day_stamp
            self.save()

    def mark_diary(self, day_stamp):
        self.data["last_diary_day"] = day_stamp
        self.save()

    def mark_memory(self, day_stamp):
        self.data["last_memory_day"] = day_stamp
        self.save()

    def mark_habits(self, window_key):
        self.data["last_habit_window"] = window_key
        self.save()

    def mark_plan(self, day_stamp):
        self.data["last_plan_day"] = day_stamp
        self.save()

    # ---- 心声 / 当前活动 ----
    def set_thought(self, text):
        self.data["thought"] = str(text or "")[:120]
        self.save()

    def set_activity(self, text):
        self.data["activity"] = str(text or "")[:80]
        self.save()

    # ---- 到访记录 ----
    def visit(self, place, day_stamp=""):
        if not place:
            return None
        visited = self.data.setdefault("visited", {})
        record = visited.get(place) or {"first": day_stamp, "last": day_stamp, "count": 0}
        record["last"] = day_stamp or record.get("last") or ""
        record["count"] = int(record.get("count") or 0) + 1
        visited[place] = record
        self.save()
        return record

    def first_visit(self, place):
        record = (self.data.get("visited") or {}).get(place) or {}
        return not record or int(record.get("count") or 0) <= 1

    def visited_text(self, limit=8):
        visited = self.data.get("visited") or {}
        items = sorted(visited.items(), key=lambda pair: int(pair[1].get("count") or 0), reverse=True)
        return "、".join("%s×%s" % (name, item.get("count")) for name, item in items[:limit])

    # ---- 计数器 ----
    def bump(self, key, step=1):
        counters = self.data.setdefault("counters", {})
        counters[key] = int(counters.get(key) or 0) + step
        self.save()
        return counters[key]

    def counter(self, key, default=0):
        try:
            return int((self.data.get("counters") or {}).get(key, default))
        except (TypeError, ValueError):
            return default

    # ---- 技能 / 职业 ----
    def set_skills(self, skills, professions=None, pending=None):
        changed = False
        if isinstance(skills, dict):
            clean = {str(key): int(value) for key, value in skills.items()
                     if str(value).lstrip("-").isdigit()}
            if clean != self.data.get("skills"):
                self.data["skills"] = clean
                changed = True
        if professions is not None:
            clean_prof = list(professions or [])
            if clean_prof != self.data.get("professions"):
                self.data["professions"] = clean_prof
                changed = True
        if pending is not None:
            if pending != self.data.get("pending_profession"):
                self.data["pending_profession"] = pending
                changed = True
        if changed:
            self.save()

    def skills_text(self):
        names = {"farming": "耕种", "mining": "采矿", "combat": "战斗",
                 "foraging": "采集", "fishing": "钓鱼", "luck": "幸运"}
        skills = self.data.get("skills") or {}
        return " · ".join("%s %s" % (names.get(key, key), value)
                          for key, value in skills.items() if key != "luck")

    # ---- 统计 ----
    def stat_add(self, key, amount=1):
        stats = self.data.setdefault("stats", {})
        stats[key] = stats.get(key, 0) + amount
        self.save()
        return stats[key]

    def snapshot(self):
        return json.loads(json.dumps(self.data, ensure_ascii=False))
