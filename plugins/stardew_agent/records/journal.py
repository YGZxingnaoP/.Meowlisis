# -*- coding: utf-8 -*-
"""当天日志：只记录，不归纳，充当模型的短期记忆。

CSV 列：time（游戏时间 HH:MM）, kind（行为/对话/心声/事件…）, content, goal。
一天一个文件 journal/<年_季_日>.csv；日志只是记录，不参与长期记忆。
"""

import csv
import os

from . import store as store_mod

HEADER = ["time", "kind", "content", "goal"]

KIND_CN = {
    "action": "行为",
    "dialogue": "对话",
    "thought": "心声",
    "event": "事件",
    "plan": "计划",
    "system": "系统",
    "share": "分享",
    "sleep": "睡觉",
}


def append(store, day_stamp, kind, content, goal="", state=None, clock=None):
    """追加一条日志，立刻落盘（崩溃也不会丢一整天）。"""
    content = str(content or "").strip().replace("\r\n", "\n")
    if not content:
        return None
    day_stamp = day_stamp or "0000_spring_00"
    path = store.journal_path(day_stamp)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new_file = not os.path.isfile(path)
    row = [
        str(clock or store_mod.game_clock(state or {})),
        str(kind or "event"),
        content,
        str(goal or ""),
    ]
    with open(path, "a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(HEADER)
        writer.writerow(row)
    return row


def read_day(store, day_stamp):
    path = store.journal_path(day_stamp)
    if not os.path.isfile(path):
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            for item in csv.DictReader(handle):
                rows.append({
                    "time": str(item.get("time") or ""),
                    "kind": str(item.get("kind") or ""),
                    "content": str(item.get("content") or ""),
                    "goal": str(item.get("goal") or ""),
                })
    except Exception:
        return []
    return rows


def recent_days(store, limit_days=2):
    """最近的日志文件，按时间正序返回 [(day_stamp, rows)]。"""
    days = sorted(store.existing_days("journal"), key=store_mod.stamp_order)
    picked = days[-max(1, int(limit_days or 1)):]
    return [(day, read_day(store, day)) for day in picked]


def render(rows, max_rows=120, max_chars=6000):
    """把日志渲染成给模型看的短文本。"""
    lines = []
    for row in (rows or [])[-max_rows:]:
        kind = KIND_CN.get(row.get("kind"), row.get("kind") or "")
        goal = ("［%s］" % row.get("goal")) if row.get("goal") else ""
        lines.append("%s %s%s：%s" % (row.get("time"), kind, goal, row.get("content")))
    text = "\n".join(lines)
    return text[:max_chars]


def render_day(store, day_stamp, max_rows=160, max_chars=8000):
    return render(read_day(store, day_stamp), max_rows=max_rows, max_chars=max_chars)


def count(store, day_stamp):
    return len(read_day(store, day_stamp))


def last_time(store, day_stamp):
    rows = read_day(store, day_stamp)
    return rows[-1]["time"] if rows else ""
