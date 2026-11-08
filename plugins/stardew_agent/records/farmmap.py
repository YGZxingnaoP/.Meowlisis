# -*- coding: utf-8 -*-
"""农场宏观记忆图：每天睡醒一张，和昨天比，给角色“田变了什么”的长期空间记忆。

不是逐格地图：mod 把农场按 4×4 格压成块，每块只记
作物 / 成熟 / 待浇 / 树 / 草 / 杂物 / 空耕地的数量。

存储（按存档隔离）：
    maps/<年_季_日>.json       当天醒来时的宏观图
    maps/diff/<年_季_日>.json  和前一天相比的变化
"""

import os

from . import store as store_mod

VERSION = 1


def _maps_dir(store):
    return store.path("maps")


def path(store, day_stamp):
    return store.path("maps", "%s.json" % day_stamp)


def diff_path(store, day_stamp):
    return store.path("maps", "diff", "%s.json" % day_stamp)


def save(store, day_stamp, data):
    data["version"] = VERSION
    data["date"] = day_stamp
    store.save_json(path(store, day_stamp), data)
    return data


def load(store, day_stamp):
    data = store.load_json(path(store, day_stamp), None)
    return data if isinstance(data, dict) and data.get("ok") else None


def previous(store, day_stamp):
    """上一天（或更早最近一张）的宏观图。"""
    directory = _maps_dir(store)
    try:
        names = [name[:-5] for name in os.listdir(directory)
                 if name.endswith(".json") and store_mod.DAY_STAMP_RE.match(name[:-5])]
    except OSError:
        return None
    now = store_mod.stamp_order(day_stamp)
    earlier = [name for name in names if store_mod.stamp_order(name) < now]
    if not earlier:
        return None
    latest = max(earlier, key=store_mod.stamp_order)
    return load(store, latest)


def _summary(data):
    summary = (data or {}).get("summary") or {}
    keys = ("crops", "ready", "thirsty", "trees", "grass", "debris", "empty_dirt")
    return {key: int(summary.get(key) or 0) for key in keys}


def diff(old, new):
    """返回汇总差值 + 变化块列表（按块坐标）。"""
    before = _summary(old)
    after = _summary(new)
    changes = {}
    for key in before:
        delta = after[key] - before[key]
        if delta:
            changes[key] = delta

    old_blocks = {}
    for block in (old or {}).get("blocks") or []:
        old_blocks[(int(block.get("x") or 0), int(block.get("y") or 0))] = block
    new_blocks = {}
    for block in (new or {}).get("blocks") or []:
        new_blocks[(int(block.get("x") or 0), int(block.get("y") or 0))] = block

    changed_blocks = []
    for key in set(old_blocks) | set(new_blocks):
        a = old_blocks.get(key) or {}
        b = new_blocks.get(key) or {}
        fields = {}
        for field in ("crop", "ready", "thirsty", "tree", "grass", "debris", "empty_dirt"):
            delta = int(b.get(field) or 0) - int(a.get(field) or 0)
            if delta:
                fields[field] = delta
        if fields:
            changed_blocks.append({"x": key[0], "y": key[1], "changes": fields})
    changed_blocks.sort(key=lambda item: (item["x"], item["y"]))
    return {
        "summary": changes,
        "blocks": changed_blocks[:60],
        "block_count": len(changed_blocks),
    }


def text(data, delta=None):
    """给提示词/日志看的短文本。"""
    if not data:
        return ""
    summary = _summary(data)
    lines = ["农场记忆图（%s，4×4 格一块）：作物 %s（熟 %s、待浇 %s）、树 %s、草 %s、杂物 %s、空耕地 %s" % (
        data.get("date") or "?",
        summary["crops"], summary["ready"], summary["thirsty"],
        summary["trees"], summary["grass"], summary["debris"], summary["empty_dirt"])]
    delta = delta or {}
    changes = delta.get("summary") or {}
    if changes:
        parts = []
        names = {"crops": "作物", "ready": "成熟", "thirsty": "待浇", "trees": "树",
                 "grass": "草", "debris": "杂物", "empty_dirt": "空耕地"}
        for key, value in changes.items():
            parts.append("%s %+d" % (names.get(key, key), value))
        lines.append("比昨天：" + "、".join(parts))
    blocks = delta.get("blocks") or []
    if blocks:
        samples = []
        for block in blocks[:6]:
            fields = []
            for key, value in (block.get("changes") or {}).items():
                fields.append("%s%+d" % (key, value))
            samples.append("(%s,%s) %s" % (block.get("x"), block.get("y"), " ".join(fields)))
        lines.append("变化的地块：" + "；".join(samples) +
                     ("（共 %d 块）" % delta.get("block_count") if delta.get("block_count", 0) > 6 else ""))
    return "\n".join(lines)
