# -*- coding: utf-8 -*-
"""生活习惯：每 7 天总结一次，不是流水账。

习惯是角色自己总结出来的「我通常在什么时间、星期几更愿意做什么」，
只作为规划时的轻量提示，不限制角色。一个 7 天窗口一个 JSON：

    habits/w00012.json
    {
      "window": {"key": "w00012", "start": "0001_spring_08", "end": "0001_spring_14",
                 "evidence_start": "0001_spring_01"},
      "habits": [
        {"content": "早上会先看电视再下地", "week_day": ["Mon", "Tue"],
         "time": ["06:00"], "priority": 4,
         "goal": "watch_tv", "reason": "7 天里有 5 天在 6~7 点打开电视"}
      ]
    }

时间窗口要够长：窗口本身是 7 天，但提取证据时看最近 14 天（evidence_start），
这样「只在某一天偶然做过一次」不会被写成习惯。
"""

import json
import os
import re

from . import store as store_mod

VERSION = 2
WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FULL = store_mod.WEEK_CN
WINDOW_DAYS = 7
EVIDENCE_DAYS = 14


def window_index(day_stamp):
    order = store_mod.stamp_order(day_stamp)
    return max(1, (max(1, order) - 1) // WINDOW_DAYS + 1)


def window_key(day_stamp):
    return "w%05d" % window_index(day_stamp)


def window_bounds(day_stamp):
    index = window_index(day_stamp)
    start_order = (index - 1) * WINDOW_DAYS + 1
    end_order = start_order + WINDOW_DAYS - 1
    return index, start_order, end_order


def window_stamps(index):
    """第 index 个 7 天窗口的起止日期戳。"""
    try:
        index = max(1, int(index))
    except (TypeError, ValueError):
        return "", ""
    start_order = (index - 1) * WINDOW_DAYS + 1
    return store_mod.stamp_from_order(start_order), store_mod.stamp_from_order(start_order + WINDOW_DAYS - 1)


def evidence_stamps(index):
    """窗口证据范围：从窗口开始往前多看 EVIDENCE_DAYS 天。"""
    try:
        index = max(1, int(index))
    except (TypeError, ValueError):
        index = 1
    end_order = index * WINDOW_DAYS
    start_order = max(1, end_order - EVIDENCE_DAYS + 1)
    return store_mod.stamp_from_order(start_order), store_mod.stamp_from_order(end_order)


def load_window(store, key):
    default = {"version": VERSION, "window": {"key": key}, "updated": 0,
               "habits": [], "evidence": {}}
    data = store.load_json(store.habit_path(key), default)
    if not isinstance(data, dict):
        data = default
    data.setdefault("habits", [])
    data.setdefault("window", {"key": key})
    data["version"] = VERSION
    return data


def save_window(store, key, data):
    data["version"] = VERSION
    data["updated"] = store_mod.now()
    store.save_json(store.habit_path(key), data)
    return data


def list_windows(store):
    return sorted(store.files("habits"))


def latest(store):
    windows = list_windows(store)
    if not windows:
        return {"version": VERSION, "window": {}, "habits": [], "evidence": {}}
    return load_window(store, windows[-1])


def today_hint(store, state):
    """当前星期 / 钟点最匹配的一条习惯，给规划和提示词用。"""
    data = latest(store)
    habits = data.get("habits") or []
    if not habits:
        return ""
    game = (state or {}).get("game") or {}
    weekday = str(game.get("day_of_week") or "")[:3].title()
    try:
        hour = int(game.get("time") or 0) // 100
    except (TypeError, ValueError):
        hour = 6
    best, best_score = None, 0.0
    for habit in habits:
        score = 0.0
        days = habit.get("week_day") or []
        if isinstance(days, str):
            days = [days]
        if not days or weekday in days or "每天" in days or "all" in days:
            score += 1.0
        for window in habit.get("time") or []:
            try:
                start = int(str(window).split(":")[0])
            except (TypeError, ValueError):
                continue
            if start <= hour <= start + 2:
                score += 1.5
        score += float(habit.get("priority") or 0) * 0.2
        if score > best_score:
            best, best_score = habit, score
    if best is None or best_score < 1.0:
        return ""
    return "%s：%s" % (best.get("content"), best.get("reason") or "")


def weights(store, state):
    """把当前时段匹配的习惯折算成轻量加权（已不再驱动规划，保留兼容）。"""
    data = latest(store)
    habits = data.get("habits") or []
    if not habits:
        return {}
    game = (state or {}).get("game") or {}
    weekday = str(game.get("day_of_week") or "")[:3].title()
    try:
        hour = int(game.get("time") or 0) // 100
    except (TypeError, ValueError):
        hour = 6
    result = {}
    for habit in habits:
        goal = str(habit.get("goal") or "").strip()
        if not goal:
            continue
        days = habit.get("week_day") or []
        if isinstance(days, str):
            days = [days]
        if days and weekday not in days and "每天" not in days and "all" not in days:
            continue
        score = 0.0
        for window in habit.get("time") or []:
            try:
                start = int(str(window).split(":")[0])
            except (TypeError, ValueError):
                continue
            if start <= hour <= start + 2:
                score += 0.06
        try:
            score += min(0.12, float(habit.get("priority") or 0) * 0.02)
        except (TypeError, ValueError):
            pass
        if score:
            result[goal] = max(result.get(goal, 0.0), score)
    return result


def normalize_habit(item):
    if not isinstance(item, dict):
        return None
    content = re.sub(r"\s+", " ", str(item.get("content") or item.get("text") or "")).strip()
    if len(content) < 3:
        return None
    days = item.get("week_day") or item.get("weekday") or []
    if isinstance(days, str):
        days = [days]
    clean_days = []
    for day in days:
        day = str(day or "").strip()
        if not day:
            continue
        if day in WEEK:
            clean_days.append(day)
        elif day in FULL.values():
            for key, value in FULL.items():
                if value == day:
                    clean_days.append(key)
    if not clean_days:
        clean_days = ["每天"]
    times = item.get("time") or []
    if isinstance(times, str):
        times = [times]
    clean_times = []
    for value in times:
        match = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", str(value))
        if match:
            hour = max(0, min(23, int(match.group(1))))
            clean_times.append("%02d:%s" % (hour, match.group(2)))
    if not clean_times:
        clean_times = ["06:00"]
    try:
        priority = max(1, min(6, int(item.get("priority") or 3)))
    except (TypeError, ValueError):
        priority = 3
    return {
        "content": content[:80],
        "week_day": clean_days[:7],
        "time": clean_times[:4],
        "priority": priority,
        "goal": str(item.get("goal") or "").strip()[:40],
        "reason": re.sub(r"\s+", " ", str(item.get("reason") or "")).strip()[:120],
    }


def save_summary(store, day_stamp, habits, evidence=None):
    key = window_key(day_stamp)
    index, start_order, end_order = window_bounds(day_stamp)
    start_stamp = store_mod.stamp_from_order(start_order)
    end_stamp = store_mod.stamp_from_order(end_order)
    evidence_start, _ = evidence_stamps(index)
    data = load_window(store, key)
    clean = []
    seen = set()
    for habit in habits or []:
        item = normalize_habit(habit)
        if not item:
            continue
        token = re.sub(r"\s+", "", item["content"])
        if token in seen:
            continue
        seen.add(token)
        clean.append(item)
    data["window"] = {
        "key": key,
        "start": start_stamp,
        "end": end_stamp,
        "evidence_start": evidence_start,
        "days": WINDOW_DAYS,
        "index": index,
    }
    data["habits"] = clean[:8]
    data["evidence"] = evidence or {}
    return save_window(store, key, data)


def render(store, limit=20):
    data = latest(store)
    habits = data.get("habits") or []
    window = data.get("window") or {}
    lines = ["# 我的生活习惯"]
    if window:
        lines.append("（%s ~ %s，证据取自 %s 起）" % (
            window.get("start", "?"), window.get("end", "?"), window.get("evidence_start", "?")))
    if not habits:
        return "\n".join(lines + ["（还不到 7 天，暂时没有总结）"])
    for habit in habits[:limit]:
        days = "、".join(FULL.get(day, day) for day in habit.get("week_day") or [])
        times = "、".join(habit.get("time") or [])
        lines.append("- %s %s：%s（重要性 %s）%s" % (
            days or "每天", times, habit.get("content"),
            habit.get("priority"), ("—— " + habit.get("reason")) if habit.get("reason") else ""))
    return "\n".join(lines)


def parse_json_habits(text):
    if not text:
        return []
    raw = str(text).strip()
    raw = re.sub(r"```[a-zA-Z]*", "", raw).replace("```", "").strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        start = raw.find("{")
        end = raw.rfind("}")
    candidate = raw[start:end + 1] if start >= 0 and end > start else raw
    try:
        data = json.loads(candidate)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("habits") or data.get("entries") or []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]
