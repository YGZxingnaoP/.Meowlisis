# -*- coding: utf-8 -*-
"""标签词表：日记 / 记忆共用的 star_tags.json。

主链逻辑里的标签是 `类别:值`（例如 `npc:Pierre`、`work:farming`），插件只维护
一份词表，避免每篇日记各写各的。add() 只补新值，不删旧值。
"""

from . import store as store_mod

CATEGORIES = {
    "npc": "和村民有关：npc:<名字>",
    "work": "劳动 / 农活 / 经营：work:<类别>",
    "event": "剧情 / 节日 / 任务：event:<事件>",
    "place": "地点 / 探索：place:<地图名>",
    "item": "物品 / 工具 / 收获：item:<物品名>",
    "mood": "心情：mood:<情绪>",
    "plan": "计划 / 目标：plan:<目标>",
    "story": "长期剧情线索：story:<线索>",
}


def _default():
    return {
        "version": 1,
        "updated": store_mod.now(),
        "categories": dict(CATEGORIES),
        "values": {},
    }


def ensure(store):
    data = store.load_json(store.tags_path(), _default())
    if not isinstance(data, dict) or "categories" not in data:
        data = _default()
    data.setdefault("values", {})
    data["updated"] = store_mod.now()
    store.save_json(store.tags_path(), data)
    return data


def normalize(tag):
    tag = str(tag or "").strip().lower()
    if not tag or ":" not in tag:
        return ""
    head = tag.split(":", 1)[0]
    return tag if head in CATEGORIES else ""


def add(store, tags):
    """把一批标签记进词表；返回词表数据。"""
    data = ensure(store)
    values = data.setdefault("values", {})
    changed = False
    for tag in tags or []:
        item = normalize(tag)
        if not item:
            continue
        bucket = values.setdefault(item.split(":", 1)[0], [])
        if item not in bucket:
            bucket.append(item)
            changed = True
    if changed:
        data["updated"] = store_mod.now()
        store.save_json(store.tags_path(), data)
    return data


def as_text(store):
    data = ensure(store)
    lines = ["# 星露谷标签表"]
    for name, note in (data.get("categories") or {}).items():
        values = (data.get("values") or {}).get(name) or []
        lines.append("- %s：%s%s" % (name, note, ("（已用：" + "、".join(values[-8:]) + "）") if values else ""))
    return "\n".join(lines)
