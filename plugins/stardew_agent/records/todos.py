# -*- coding: utf-8 -*-
"""待办条目：用户消息 / 语音 / 弹幕给的建议，以及角色自己突发奇想记下的事。

一天一个 JSON：

    todos/0001_spring_03.json
    {
      "date": "0001_spring_03",
      "items": [
        {"id": "t1", "content": "去矿洞看看老人说的石剑",
         "source": "qq:1149942002", "by": "主人",
         "necessity": 7, "priority": 8, "frequency": "once",
         "status": "open", "created": 1760000000,
         "action": {"goal": "explore_mine", "params": {}}}
      ]
    }

每个条目都有必要性 / 优先级 / 频率，方便当日计划挑。
"""

import re

from . import store as store_mod

VERSION = 2
STATUSES = ("open", "doing", "done", "dropped", "deferred")
FREQUENCIES = ("once", "daily", "weekly", "seasonal")


def _clip(text, limit=160):
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _norm(text):
    return re.sub(r"[\s，。；、,.!?！？：:（）()“”\"'·\-]+", "", str(text or "")).lower()


def _same_task(left, right):
    a, b = _norm(left), _norm(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
        return True
    return False


def complete_like(store, day_stamp, item_id):
    """勾掉一条待办时，把同一天里重复/包含的同义待办一起勾掉。"""
    data = load_day(store, day_stamp)
    target = None
    for item in data.get("items") or []:
        if item.get("id") == item_id:
            target = item
            break
    if target is None:
        return []
    done = []
    for item in data.get("items") or []:
        if item.get("status") not in ("open", "doing", "deferred"):
            continue
        if item is target or _same_task(item.get("content"), target.get("content")):
            item["status"] = "done"
            item["updated"] = store_mod.now()
            done.append(item)
    save_day(store, day_stamp, data)
    return done


def _num(value, default, low=1, high=10):
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _frequency(value):
    value = str(value or "").strip().lower()
    if value in FREQUENCIES:
        return value
    return {"每天": "daily", "每日": "daily", "每周": "weekly", "每季": "seasonal",
            "一次": "once", "一次性": "once"}.get(value, "once")


def _status(value):
    value = str(value or "").strip().lower()
    return value if value in STATUSES else "open"


def normalize_item(item, day_stamp=""):
    if not isinstance(item, dict):
        return None
    content = _clip(item.get("content") or item.get("text") or "")
    if not content:
        return None
    action = item.get("action")
    if isinstance(action, str):
        action = {"goal": action}
    if not isinstance(action, dict):
        action = {}
    return {
        "id": _clip(item.get("id"), 40) or "t%d" % (store_mod.now() % 1000000),
        "content": content,
        "source": _clip(item.get("source") or "self", 60),
        "by": _clip(item.get("by") or "", 40),
        "necessity": _num(item.get("necessity"), 5),
        "priority": _num(item.get("priority"), 5),
        "frequency": _frequency(item.get("frequency")),
        "status": _status(item.get("status")),
        "created": int(item.get("created") or store_mod.now()),
        "updated": store_mod.now(),
        "due": _clip(item.get("due") or "", 20),
        "note": _clip(item.get("note") or "", 120),
        "goal": _clip(item.get("goal") or action.get("goal") or "", 40),
        "action": {
            "goal": _clip(action.get("goal") or item.get("goal") or "", 40),
            "params": action.get("params") if isinstance(action.get("params"), dict) else {},
        },
        "day": day_stamp,
    }


def load_day(store, day_stamp):
    default = {"version": VERSION, "date": day_stamp, "updated": 0, "items": []}
    data = store.load_json(store.todo_path(day_stamp), default)
    if not isinstance(data, dict):
        data = default
    data.setdefault("items", [])
    data["version"] = VERSION
    return data


def save_day(store, day_stamp, data):
    data["version"] = VERSION
    data["date"] = day_stamp
    data["updated"] = store_mod.now()
    store.save_json(store.todo_path(day_stamp), data)
    return data


def add(store, day_stamp, item):
    data = load_day(store, day_stamp)
    clean = normalize_item(item, day_stamp)
    if not clean:
        return None
    for old in data["items"]:
        if old.get("content") == clean["content"] and old.get("status") in ("open", "doing"):
            old["necessity"] = max(int(old.get("necessity") or 0), clean["necessity"])
            old["priority"] = max(int(old.get("priority") or 0), clean["priority"])
            old["updated"] = store_mod.now()
            save_day(store, day_stamp, data)
            return old
    data["items"].append(clean)
    save_day(store, day_stamp, data)
    return clean


def update_status(store, day_stamp, item_id, status, note=""):
    data = load_day(store, day_stamp)
    for item in data["items"]:
        if item.get("id") == item_id:
            item["status"] = _status(status)
            item["updated"] = store_mod.now()
            if note:
                item["note"] = _clip(note, 120)
            save_day(store, day_stamp, data)
            return item
    return None


def open_items(store, day_stamp):
    data = load_day(store, day_stamp)
    return [item for item in data["items"] if item.get("status") in ("open", "doing")]


def summary(store, day_stamp, max_items=12):
    data = load_day(store, day_stamp)
    items = data.get("items") or []
    if not items:
        return "今天没有待办。"
    lines = []
    for item in items[:max_items]:
        mark = {"done": "✔", "dropped": "×", "doing": "…", "deferred": "»"}.get(item.get("status"), "·")
        source = ("（%s）" % item.get("by")) if item.get("by") else ""
        lines.append("%s %s%s 必要%s/优先%s/%s" % (
            mark, item.get("content"), source, item.get("necessity"),
            item.get("priority"), item.get("frequency")))
    return "\n".join(lines)


def render(store, day_stamp, max_items=20):
    return "# 待办\n" + summary(store, day_stamp, max_items)


def carry_over(store, from_stamp, to_stamp, limit=20):
    """把上一天没做完的待办搬到今天；不复制已完成/已丢弃的。"""
    if not from_stamp or from_stamp == to_stamp:
        return []
    data = load_day(store, from_stamp)
    moved = []
    for item in (data.get("items") or [])[:limit]:
        if item.get("status") not in ("open", "doing", "deferred"):
            continue
        copy = dict(item)
        copy["id"] = "t%d" % (store_mod.now() % 1000000 + len(moved))
        copy["day"] = to_stamp
        copy["source"] = str(item.get("source") or "") + "+carry"
        copy["created"] = store_mod.now()
        copy["updated"] = store_mod.now()
        moved.append(copy)
    if moved:
        target = load_day(store, to_stamp)
        existing = {item.get("content") for item in target.get("items") or []}
        for item in moved:
            if item.get("content") in existing:
                continue
            target["items"].append(item)
        save_day(store, to_stamp, target)
    return moved


def to_plan_node(item, prefix="todo"):
    """把高优先级待办直接塞进当日计划树。"""
    if not isinstance(item, dict):
        return None
    return {
        "title": item.get("content"),
        "detail": "来自 %s" % (item.get("by") or item.get("source") or "待办"),
        "necessity": item.get("necessity", 5),
        "priority": item.get("priority", 5),
        "frequency": item.get("frequency", "once"),
        "status": "pending",
        "source": "todo:%s" % item.get("id"),
        "action": item.get("action") or {},
    }


def parse_json_items(text):
    if not text:
        return []
    raw = re.sub(r"```[a-zA-Z]*", "", str(text)).replace("```", "").strip()
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        start, end = raw.find("{"), raw.rfind("}")
    candidate = raw[start:end + 1] if start >= 0 and end > start else raw
    try:
        import json
        data = json.loads(candidate)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("todos") or data.get("items") or []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]
