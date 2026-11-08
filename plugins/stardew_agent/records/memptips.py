# -*- coding: utf-8 -*-
"""长期记忆 tips（只属于星露谷插件）。

和日志 / 日记的区别：
    - 日志：当天流水，原样记录，是短期记忆；
    - 日记：当天总结，有角色口吻；
    - 记忆：极其精简、长期有价值、能直接被召回并影响判断的 tips。

存储：一条 tip 一个独立 JSON，放在 memory/ 下，文件名
`<年_季_日>_<序号>.json`，内容不是按天分组，跨季节统一召回：

    {
      "content": "Pierre 是镇上杂货店老板，喜欢防风草。",
      "time": "0001_spring_03",
      "tag": ["npc"],
      "attributes": {"accuracy": 3, "value": 8,
                     "npc": "Pierre", "friendship": 4, "relationship": "店主/熟人"}
    }

硬规则（写入时校验，不合格直接丢掉）：
    - 不写日期和相对时间（今天/昨天/第X天/早上…）；
    - 不写一次性流水账（种了几颗、浇了水、体力多少、天气、赚了多少）；
    - 每条不超过 80 字；重复内容不重复写；
    - npc 类必须带 npc 名字，content 里也要出现这个名字。
"""

import json
import os
import re
import time

from . import store as store_mod

VERSION = 1
SOFT_LEN = 80
HARD_LEN = 150
DIMENSIONS = ("npc", "work", "event")

ALLOWED_TAGS = {
    "npc": "和某个村民有关（必须带 npc / friendship / relationship）",
    "work": "自己长期做的一类劳动、经营、农场布局",
    "event": "剧情、节日、任务、探索发现",
}

# 有时间性 / 一次性流水账特征的句子一律不算长期记忆。
TRANSIENT_PATTERNS = (
    r"今天", r"今日", r"刚才", r"现在", r"目前", r"这周", r"本周", r"这个季节",
    r"种了\s*\d+", r"浇了\s*\d+", r"收了\s*\d+", r"赚了\s*\d+", r"\d+\s*个",
    r"第\s*\d+\s*天", r"天气", r"下雨", r"体力", r"金币\s*\d+",
    r"昨天", r"明天", r"早上", r"晚上", r"上午", r"下午",
)

_FILENAME_RE = re.compile(r"^(\d{4}_[a-z]+_\d{2})_(\d{3})$")


def _clip(text, limit=HARD_LEN):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) > limit:
        text = text[:limit].rstrip("，。；、 ") + "…"
    return text


def _norm(text):
    return re.sub(r"[\s，。；、,.!?！？：:（）()“”\"'·\-]+", "", str(text or "")).lower()


def is_transient(content):
    text = str(content or "")
    return any(re.search(pattern, text) for pattern in TRANSIENT_PATTERNS)


def _safe_name(text):
    return store_mod.safe(text, 40)


def normalize_tip(tip, day_stamp=""):
    """把模型 / 规则给的一条 tip 校验成固定结构；不合格返回 None。"""
    if not isinstance(tip, dict):
        return None
    content = _clip(tip.get("content") or tip.get("text") or "")
    if len(content) < 4 or is_transient(content):
        return None
    tags = tip.get("tag") or tip.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    tags = [str(tag).strip().lower() for tag in tags if str(tag).strip()]
    tags = [tag for tag in tags if tag in ALLOWED_TAGS]
    if not tags:
        if re.search(r"和|跟|送|聊|喜欢|关系|好感", content):
            tags = ["npc"]
        elif re.search(r"矿|鱼|田|农|种|工具|商店|钱|出货|建造", content):
            tags = ["work"]
        else:
            tags = ["event"]
    attrs = tip.get("attributes") or tip.get("attrs") or {}
    if not isinstance(attrs, dict):
        attrs = {}
    try:
        accuracy = max(1, min(3, int(attrs.get("accuracy") or 2)))
    except (TypeError, ValueError):
        accuracy = 2
    try:
        value = max(1, min(10, int(attrs.get("value") or 5)))
    except (TypeError, ValueError):
        value = 5
    clean_attrs = {"accuracy": accuracy, "value": value}
    if "npc" in tags:
        npc = str(attrs.get("npc") or tip.get("npc") or "").strip()
        if not npc:
            return None
        if npc not in content:
            return None
        clean_attrs["npc"] = _clip(npc, 20)
        try:
            clean_attrs["friendship"] = max(0, min(14, int(attrs.get("friendship") or 0)))
        except (TypeError, ValueError):
            clean_attrs["friendship"] = 0
        clean_attrs["relationship"] = _clip(attrs.get("relationship") or "认识", 30)
    for key in ("place", "item", "source", "reason"):
        if attrs.get(key):
            clean_attrs[key] = _clip(attrs.get(key), 40)
    stamp = str(day_stamp or "").strip() or "0000_spring_00"
    return {
        "content": content,
        "time": stamp,
        "tag": tags,
        "attributes": clean_attrs,
    }


def _paths(store):
    directory = store.memory_dir()
    result = []
    try:
        for name in os.listdir(directory):
            stem = name[:-5] if name.endswith(".json") else name
            match = _FILENAME_RE.match(stem)
            if not match:
                continue
            result.append((match.group(1), int(match.group(2)), os.path.join(directory, name)))
    except OSError:
        return []
    result.sort(key=lambda item: (store_mod.stamp_order(item[0]), item[1]))
    return result


def all_tips(store):
    """按时间正序返回全部 tips（面板 / 召回用）。"""
    result = []
    for _day, _index, path in _paths(store):
        data = store.load_json(path, None)
        if isinstance(data, dict) and str(data.get("content") or "").strip():
            data.setdefault("id", os.path.basename(path)[:-5])
            result.append(data)
    return result


def _next_index(store, day_stamp):
    highest = 0
    for day, index, _path in _paths(store):
        if day == day_stamp:
            highest = max(highest, index)
    return highest + 1


def _duplicate(tips, content):
    target = _norm(content)
    if not target:
        return True
    for old in tips:
        if _norm(old.get("content")) == target:
            return True
    return False


def replace_day(store, day_stamp, tips):
    """用当天睡前总结的结果替换当天 tips：先删掉这一天旧的，再写新的（重复运行不会堆）。"""
    directory = store.memory_dir()
    for day, _index, path in _paths(store):
        if day == day_stamp:
            try:
                os.remove(path)
            except OSError:
                pass
    return add_day(store, day_stamp, tips)


def add_day(store, day_stamp, tips):
    """追加当天的 tips；去重后每条写一个独立 JSON。"""
    existing = all_tips(store)
    directory = store.memory_dir()
    os.makedirs(directory, exist_ok=True)
    added = []
    index = _next_index(store, day_stamp)
    for tip in tips or []:
        item = normalize_tip(tip, day_stamp)
        if not item:
            continue
        if _duplicate(existing + added, item["content"]):
            continue
        item["id"] = "%s_%03d" % (day_stamp, index)
        store.save_json(os.path.join(directory, "%s_%03d.json" % (day_stamp, index)), item)
        added.append(item)
        index += 1
    if added:
        try:
            from . import tags
            tags.add(store, [tag for item in added for tag in item.get("tag") or []])
        except Exception:
            pass
    return added


def recall(store, limit=8, tags_wanted=None, query="", current_stamp="", max_tips=400):
    """按标签 / 关键词 / 价值 / 新旧召回；越新、越有价值越靠前。"""
    wanted = set(tags_wanted or [])
    query_tokens = [token for token in re.split(r"[\s,，。；;]+", str(query or "")) if token]
    now_order = store_mod.stamp_order(current_stamp) if current_stamp else 0
    scored = []
    for tip in all_tips(store)[-max_tips:]:
        tip_tags = set(tip.get("tag") or [])
        if wanted and not (wanted & tip_tags):
            continue
        attrs = tip.get("attributes") or {}
        try:
            value = float(attrs.get("value") or 5)
            accuracy = float(attrs.get("accuracy") or 2)
        except (TypeError, ValueError):
            value, accuracy = 5.0, 2.0
        score = value + accuracy * 0.6
        if query_tokens:
            haystack = "%s %s" % (tip.get("content") or "", " ".join(tip_tags))
            hits = sum(1 for token in query_tokens if token and token in haystack)
            score += hits * 2.5
        if now_order:
            age = max(0, now_order - store_mod.stamp_order(tip.get("time") or ""))
            score -= min(6.0, age * 0.06)
        scored.append((score, tip))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [tip for _score, tip in scored[:limit]]


def render(tips, max_items=20, with_meta=True):
    lines = ["# 我的星露谷记忆"]
    if not tips:
        return "\n".join(lines + ["（还没有值得记住的事）"])
    for tip in tips[:max_items]:
        attrs = tip.get("attributes") or {}
        if not with_meta:
            lines.append("- " + str(tip.get("content") or ""))
            continue
        tags = "/".join(tip.get("tag") or [])
        meta = tags or "memory"
        if "npc" in (tip.get("tag") or []):
            meta += "·%s·好感%s" % (attrs.get("npc") or "?", attrs.get("friendship", "?"))
        lines.append("- （%s）%s" % (meta, tip.get("content") or ""))
    return "\n".join(lines)


def render_store(store, limit=20, current_stamp=""):
    return render(recall(store, limit=limit, current_stamp=current_stamp))


def stats(store):
    total = 0
    by_tag = {}
    for tip in all_tips(store):
        total += 1
        for tag in tip.get("tag") or []:
            by_tag[tag] = by_tag.get(tag, 0) + 1
    return {"total": total, "by_tag": by_tag}


def parse_json_tips(text):
    """从模型输出里抠出 tips 数组；容忍一层 {"tips": [...]} 包装。"""
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
        data = data.get("tips") or data.get("memories") or data.get("entries") or []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]
