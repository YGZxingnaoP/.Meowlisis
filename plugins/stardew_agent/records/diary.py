# -*- coding: utf-8 -*-
"""日记：每天睡前写完，然后才睡觉。

一天一个 JSON（不是 markdown），字段固定：

    diary/0001_spring_03.json
    {
      "date": "0001_spring_03", "year": 1, "season": "spring", "day": 3,
      "weather": "晴", "mood": "挺满足的",
      "content": "今天……",
      "summary": "一句话摘要",
      "tags": ["npc:Pierre", "work:farming"],
      "created": 1760000000
    }

正文引导模型写 100 字左右，硬上限 200 字（超出截断）。日记不是动作日志，
要有角色自己的评价、情绪和之后的打算，但必须基于当天事实，不能乱编。
"""

import re

from . import store as store_mod

VERSION = 2
GUIDE_CHARS = 100
HARD_CHARS = 200
SEASON_CN = store_mod.SEASON_CN


def weather_text(state):
    game = (state or {}).get("game") or {}
    if game.get("snowing"):
        return "雪天"
    if game.get("raining"):
        return "雨天"
    return "晴天"


def _clip(text):
    text = re.sub(r"\s+", "", str(text or "")).strip()
    if len(text) > HARD_CHARS:
        text = text[:HARD_CHARS].rstrip("，。；、 ") + "…"
    return text


def date_text(day_stamp):
    parts = str(day_stamp or "").split("_")
    if len(parts) < 3:
        return str(day_stamp or "")
    try:
        year = int(parts[0])
        day = int(parts[2])
    except (TypeError, ValueError):
        return str(day_stamp)
    return "第 %s 年 %s %s 日" % (year, SEASON_CN.get(parts[1], parts[1]), day)


def write(store, day_stamp, content, state=None, mood="", summary="", tags=None, meta=None):
    """写当天日记；已存在则覆盖（同一天重复写只会保留最后一版）。"""
    body = _clip(content)
    if not body:
        return None
    game = (state or {}).get("game") or {}
    try:
        year = int(game.get("year") or str(day_stamp).split("_")[0])
    except (TypeError, ValueError):
        year = 0
    data = {
        "version": VERSION,
        "date": str(day_stamp),
        "year": year,
        "season": str(game.get("season") or (str(day_stamp).split("_") + ["?"])[1]),
        "day": int(game.get("day") or store_mod.day_of(day_stamp)),
        "weather": weather_text(state),
        "mood": str(mood or "")[:30],
        "content": body,
        "summary": _clip(summary)[:120] if summary else body[:60],
        "tags": [str(tag).strip().lower() for tag in (tags or []) if str(tag).strip()][:8],
        "created": store_mod.now(),
        "meta": meta or {},
    }
    store.save_json(store.diary_path(day_stamp), data)
    try:
        from . import tags
        tags.add(store, data.get("tags") or [])
    except Exception:
        pass
    return data


def read(store, day_stamp):
    data = store.load_json(store.diary_path(day_stamp), None)
    if isinstance(data, dict) and data.get("content"):
        return data
    return None


def exists(store, day_stamp):
    return read(store, day_stamp) is not None


def list_days(store, limit=20):
    days = store.existing_days("diary")
    days = sorted(days, key=store_mod.stamp_order, reverse=True)
    return days[:max(1, int(limit or 1))]


def latest(store, before=""):
    days = sorted(store.existing_days("diary"), key=store_mod.stamp_order)
    if before:
        days = [day for day in days if store_mod.stamp_order(day) < store_mod.stamp_order(before)]
    for day in reversed(days):
        data = read(store, day)
        if data:
            return day, data
    return "", None


SEARCH_SPLIT = re.compile(r"[\s,，;；、/|]+")
SEARCH_STOPWORDS = {
    "今天", "昨天", "明天", "后天", "现在", "目前", "这周", "本周", "这个", "那个",
    "自己", "什么", "可以", "还是", "已经", "没有", "一个", "一些", "时候", "事情",
    "the", "and", "for", "with", "this", "that",
}


def _search_terms(query):
    terms = []
    for chunk in SEARCH_SPLIT.split(str(query or "").lower()):
        chunk = chunk.strip()
        if len(chunk) < 2 or chunk in SEARCH_STOPWORDS:
            continue
        if chunk not in terms:
            terms.append(chunk)
    return terms


def _search_tags(tags):
    if isinstance(tags, str):
        tags = SEARCH_SPLIT.split(tags)
    result = []
    for tag in tags or []:
        tag = str(tag or "").strip().lower()
        if tag and tag not in result:
            result.append(tag)
    return result


def _tag_match(wanted, actual):
    wanted = str(wanted or "").strip().lower()
    actual = str(actual or "").strip().lower()
    if not wanted or not actual:
        return False
    return (wanted == actual or actual.startswith(wanted + ":")
            or wanted.startswith(actual + ":") or wanted in actual)


def _score(data, terms, wanted_tags):
    content = str(data.get("content") or "").lower()
    summary = str(data.get("summary") or "").lower()
    mood = str(data.get("mood") or "").lower()
    date_line = date_text(data.get("date")).lower()
    diary_tags = [str(tag).lower() for tag in data.get("tags") or []]
    score = 0.0
    tag_filter_hit = False
    for wanted in wanted_tags:
        for tag in diary_tags:
            if _tag_match(wanted, tag):
                score += 5.0
                tag_filter_hit = True
                break
    for term in terms:
        if term in content:
            score += 3.0
        elif term in summary:
            score += 2.0
        elif term in mood:
            score += 1.5
        elif term in date_line:
            score += 1.0
        elif any(term in tag for tag in diary_tags):
            score += 4.0
        else:
            grams = [term[start:start + 2] for start in range(len(term) - 1)]
            if len(grams) >= 2:
                hits = sum(1 for gram in grams if gram in content or gram in summary)
                if hits >= 2:
                    score += 2.0
    return score, tag_filter_hit


def search(store, query="", tags=None, limit=3, before=""):
    """在历史日记里按关键词 / 标签检索，返回日记 dict 列表（按相关度、日期倒序）。"""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 3
    if limit <= 0:
        return []
    limit = min(limit, 20)
    terms = _search_terms(query)
    wanted_tags = _search_tags(tags)
    before_order = store_mod.stamp_order(before) if before else 0
    scored = []
    for day in store.existing_days("diary"):
        if before_order and store_mod.stamp_order(day) >= before_order:
            continue
        data = read(store, day)
        if not data:
            continue
        if not terms and not wanted_tags:
            scored.append((0.0, day, data))
            continue
        score, tag_filter_hit = _score(data, terms, wanted_tags)
        if wanted_tags and not tag_filter_hit:
            continue
        if terms and score < 2.0:
            continue
        scored.append((score, day, data))
    scored.sort(key=lambda item: (-item[0], -store_mod.stamp_order(item[1])))
    return [data for _score_value, _day, data in scored[:limit]]


def render(data, with_meta=True):
    if not data:
        return ""
    header = "# %s" % date_text(data.get("date"))
    meta = []
    if with_meta:
        meta.append(data.get("weather") or "")
        if data.get("mood"):
            meta.append("心情：" + str(data.get("mood")))
        if data.get("tags"):
            meta.append("标签：" + "、".join(data.get("tags")))
    lines = [header]
    if any(meta):
        lines.append("（%s）" % " · ".join([m for m in meta if m]))
    lines.append(str(data.get("content") or ""))
    return "\n".join(lines)


def fallback_content(rows, state=None):
    """没有模型时的日记兜底：按事实写一小段，不假装有文采。"""
    meaningful = [row for row in (rows or []) if row.get("kind") in ("action", "dialogue", "event", "thought")]
    pieces = []
    actions = [row for row in meaningful if row.get("kind") == "action"]
    dialogue = [row for row in meaningful if row.get("kind") == "dialogue"]
    thoughts = [row for row in meaningful if row.get("kind") == "thought"]
    if actions:
        text = "、".join(str(row.get("content") or "").rstrip("。；; ") for row in actions[:3])
        pieces.append("今天" + text + "。")
    if dialogue:
        text = "；".join(str(row.get("content") or "").rstrip("。；; ") for row in dialogue[:2])
        pieces.append("见了人，" + text + "。")
    if thoughts:
        pieces.append("心里想着：" + str(thoughts[-1].get("content"))[:40] + "。")
    if not pieces:
        pieces.append("今天没什么特别的，在农场待着，看看天，想想明天。")
    pieces.append("明天想把没做完的事接着做。")
    return _clip("".join(pieces))


def parse_tags(text):
    if not text:
        return []
    tokens = re.split(r"[\s,，;；]+", str(text))
    return [token for token in tokens if ":" in token][:8]
