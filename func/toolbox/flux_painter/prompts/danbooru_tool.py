# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/prompts/danbooru_tool.py
# danbooru 角色 tag 查询工具：交给 LLM 自己调，而不是代码里猜关键词。
#
# 为什么是工具：模型知道角色，但 tag 写法（`shiroko (blue archive)` / `chiz (nte)`）
# 必须查准；把「查」这一步交给 LLM 决定何时查、查什么，比在代码里硬编码关键词可靠。
#
# 结果落盘缓存：`.vendor/.ComfyNode/prompt_reference/danbooru_tags.json`
#   · 命中且未过期 → 直接用，不再联网；
#   · 联网失败但有过期缓存 → 用旧缓存（标注「离线缓存」），保证断网也能画；
#   · 查询失败不入缓存，避免把失败钉死。
import json
import os
import re
import time
import urllib.parse
import urllib.request

API = "https://danbooru.donmai.us/tags.json"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
      "Accept": "application/json"}

CACHE_NAME = "danbooru_tags.json"
CACHE_TTL = 30 * 24 * 3600        # 30 天
CACHE_MAX = 2000                  # 条数上限

DANBOORU_TAG_TOOL = {
    "type": "function",
    "function": {
        "name": "danbooru_tag",
        "description": (
            "查 danbooru 角色 tag 的准确写法并返回候选（含作品括注与图片数量）。"
            "需求里点名了角色时**先调用它**，拿到形如 `shiroko (blue archive)` 的 tag 再写提示词；"
            "查不到/网络失败就用你已知的名字，不要编造括注。"),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "角色英文名或罗马音，如 mika / shiroko / chiz / hu tao"},
                "series": {"type": "string",
                           "description": "作品英文名（可选），如 blue archive / arknights / "
                                          "zenless zone zero / genshin impact"},
            },
            "required": ["query"],
        },
    },
}


def _cache_path(config=None):
    """缓存文件路径：优先 config 指定，否则放在 prompt_reference 下。"""
    explicit = str(getattr(config, "danbooru_cache_file", "") or "").strip()
    if explicit:
        return explicit
    base = str(getattr(config, "comfy_node_dir", "") or ".vendor/.ComfyNode").strip()
    return os.path.join(base, "prompt_reference", CACHE_NAME)


def _load_cache(path):
    """读缓存；坏文件当空表。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(path, data):
    """原子写缓存：先写 .tmp 再替换，并裁到 CACHE_MAX 条。"""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if len(data) > CACHE_MAX:
            items = sorted(data.items(), key=lambda kv: kv[1].get("ts") or 0, reverse=True)
            data = dict(items[:CACHE_MAX])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        pass


def _key(query, series):
    """缓存键：查询词 + 作品（小写归一）。"""
    return "%s|%s" % (str(query).strip().lower(), str(series).strip().lower())


def _fmt(rows, cached=False, stale=False):
    """把候选整理成喂给 LLM 的文本。"""
    lines = ["danbooru 候选（按图片数排序，tag 请照抄，括注保留）："]
    for count, name in rows:
        lines.append("- %s（%d 张）" % (name, count))
    if cached:
        lines.append("（本地缓存）")
    elif stale:
        lines.append("（离线缓存：本次联网失败，用的是旧数据）")
    return "\n".join(lines)


def run(args, config=None, log=None, timeout=None):
    """执行查询，返回喂回给 LLM 的文本（失败也只返回说明，不抛异常）。"""
    args = args or {}
    q = str(args.get("query") or "").strip()
    series = str(args.get("series") or "").strip().lower()
    if not q:
        return "（缺少 query：请给出角色英文名）"
    if config is not None and not getattr(config, "danbooru_lookup", True):
        return "（danbooru 查询已关闭，请直接使用你已知的角色名）"

    path = _cache_path(config)
    cache = _load_cache(path)
    key = _key(q, series)
    hit = cache.get(key) or {}
    if hit.get("rows") and (time.time() - float(hit.get("ts") or 0)) < CACHE_TTL:
        if log:
            log.info("[flux_painter] danbooru 命中缓存：%s → %s"
                     % (q, hit.get("best") or hit["rows"][0][1]))
        return _fmt([(r[0], r[1]) for r in hit["rows"]][:10], cached=True)

    timeout = timeout or max(3, int(getattr(config, "danbooru_timeout", 8) or 8))
    url = API + "?" + urllib.parse.urlencode({
        "search[name_matches]": "%s*" % q.replace("_", " "),
        "search[order]": "count",
        "limit": 10,
    })
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        if log:
            log.info("[flux_painter] danbooru 工具查询失败: %s" % type(e).__name__)
        if hit.get("rows"):
            return _fmt([(r[0], r[1]) for r in hit["rows"]], stale=True)
        return "（danbooru 查询失败：%s；请用你已知的官方名继续，不要编造）" % type(e).__name__

    rows = []
    for item in (data if isinstance(data, list) else []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").replace("_", " ")
        if not name:
            continue
        count = int(item.get("post_count") or 0)
        if series and series.replace("_", " ") not in name.lower():
            continue
        rows.append((count, name))
    rows.sort(reverse=True)
    if not rows:
        return ("（danbooru 没有匹配 `%s` 的 tag；请用你已知的官方英文名，"
                "不要编造作品括注）" % q)

    cache[key] = {"ts": time.time(), "query": q, "series": series,
                  "rows": [[c, n] for c, n in rows[:10]],
                  "best": rows[0][1]}
    _save_cache(path, cache)
    if log:
        log.info("[flux_painter] danbooru 工具命中 %d 条：%s（已写缓存）" % (len(rows), rows[0][1]))
    return _fmt(rows[:10])
