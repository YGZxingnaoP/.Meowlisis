# -*- coding: utf-8 -*-
import json
import os
import time
import urllib.parse
import urllib.request

API = "https://danbooru.donmai.us/tags.json"
POSTS_API = "https://danbooru.donmai.us/posts.json"
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

def verify_tag(tag, config=None, log=None):
    """查证一个角色 tag 是否真实存在；返回 (是否可信, 规范写法)。"""
    raw = str(tag or "").strip().lower()
    if not raw:
        return False, ""
    name = raw.split("(")[0].strip()
    if not name:
        return False, ""
    base_series = raw[len(name):].strip().strip("()")
    path = _cache_path(config)
    cache = _load_cache(path)
    for key, entry in cache.items():
        if not key.startswith(name):
            continue
        rows = entry.get("rows") or []
        for _count, row_name in rows:
            row_low = str(row_name).lower()
            if row_low == raw:
                return True, row_name
            if base_series and base_series in row_low:
                return True, row_name
    out = run({"query": name, "series": base_series}, config=config, log=log)
    if out.startswith("（danbooru 查询失败") or "没有匹配" in out:
        return False, ""
    for line in out.splitlines():
        if not line.startswith("- "):
            continue
        cand = line[2:].split("（")[0].strip()
        if cand.lower() == raw:
            return True, cand
    return False, ""

TOP_TAGS_NAME = "danbooru_character_tags.json"
STOP_TAGS = {
    "solo", "1girl", "1boy", "2girls", "multiple_girls", "highres", "absurdres",
    "looking_at_viewer", "simple_background", "white_background", "transparent_background",
    "commentary", "english_commentary", "translated", "artist_name", "signature",
    "watermark", "web_address", "dated", "official_art", "sketch", "monochrome",
}


def top_tags(tag, config=None, log=None, timeout=None, limit=120):
    """抓该角色最常见的画面 tag（发色/瞳色/服装等），带磁盘缓存。

    返回 (ok, tags)；tags 是 danbooru 统计出来的高频 tag，不是猜的。
    """
    raw = str(tag or "").strip().lower()
    if not raw:
        return False, []
    base = str(getattr(config, "comfy_node_dir", "") or ".vendor/.ComfyNode").strip()
    path = os.path.join(base, "prompt_reference", TOP_TAGS_NAME)
    cache = {}
    try:
        cache = json.load(open(path, encoding="utf-8"))
    except Exception:
        cache = {}
    hit = cache.get(raw) or {}
    if hit.get("tags"):
        return True, list(hit["tags"])

    url = POSTS_API + "?" + urllib.parse.urlencode({
        "tags": "%s solo" % raw, "limit": limit, "only": "tag_string"})
    rows = _http_json(url, timeout=timeout or 10, log=log,
                      cookie=str(getattr(config, "danbooru_cookie", "") or ""),
                      ua=str(getattr(config, "danbooru_user_agent", "") or ""))
    if rows is None:
        if log:
            log.info("[flux_painter] danbooru 角色 tag 统计失败（网络/被拦）")
        return (bool(hit.get("tags")), list(hit.get("tags") or []))

    counter = {}
    for row in (rows if isinstance(rows, list) else []):
        for t in str((row or {}).get("tag_string") or "").split():
            t = t.strip().lower()
            if not t or t in STOP_TAGS or t.endswith("_(cosplay)"):
                continue
            if "(" in t and ")" in t:
                continue
            counter[t] = counter.get(t, 0) + 1
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    tags = [t for t, n in ranked if n >= max(3, limit // 10)][:12]
    if tags:
        cache[raw] = {"ts": time.time(), "tags": tags}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            json.dump(cache, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception:
            pass
        if log:
            log.info("[flux_painter] danbooru 角色高频 tag(%s): %s" % (raw, ", ".join(tags[:6])))
    return (bool(tags), tags)


def _clean_cookie(raw):
    """把 DevTools 复制的整串 cookie 洗成合法 Cookie 头（丢掉 domain/path/expires 等属性）。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    pairs = []
    for part in text.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name.lower() in ("domain", "path", "expires", "max-age", "secure",
                            "httponly", "samesite", "priority"):
            continue
        pairs.append("%s=%s" % (name, value.strip()))
    return "; ".join(pairs)


def _http_json(url, timeout=10, log=None, cookie="", ua=""):
    """取 JSON：优先 curl_cffi（浏览器 TLS 指纹，过 Cloudflare），再 urllib/curl。"""
    import subprocess
    try:
        from curl_cffi import requests as cffi_requests
        headers = dict(UA)
        if ua:
            headers["User-Agent"] = ua
        cookie = _clean_cookie(cookie)
        if cookie:
            headers["Cookie"] = cookie
        r = cffi_requests.get(url, headers=headers, impersonate="chrome",
                              timeout=timeout)
        if r.status_code == 200:
            return r.json()
        if log:
            log.info("[flux_painter] curl_cffi 状态 %s，改用其他方式" % r.status_code)
    except Exception:
        pass
    try:
        headers = dict(UA)
        if ua:
            headers["User-Agent"] = ua
        cookie = _clean_cookie(cookie)
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        code = getattr(e, "code", None)
        if log:
            log.info("[flux_painter] urllib 取数失败(%s), 改用 curl" % (code or type(e).__name__))
    try:
        out = subprocess.run(
            ["curl", "-sS", "--compressed", "--max-time", str(int(timeout)),
             "-H", "User-Agent: " + (ua or UA["User-Agent"]),
             "-H", "Accept: application/json"]
            + (["-H", "Cookie: " + _clean_cookie(cookie)] if cookie else []) + [url],
            capture_output=True, timeout=timeout + 5)
        text = (out.stdout or b"").decode("utf-8", "ignore").strip()
        if text.startswith("[") or text.startswith("{"):
            return json.loads(text)
        if log:
            log.info("[flux_painter] curl 也未取到数据: %s" % (text[:80] or out.stderr[:80]))
    except Exception as e:
        if log:
            log.info("[flux_painter] curl 兜底失败: %s" % type(e).__name__)
    return None


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
    data = _http_json(url, timeout=timeout, log=log,
                      cookie=str(getattr(config, "danbooru_cookie", "") or ""),
                      ua=str(getattr(config, "danbooru_user_agent", "") or ""))
    if data is None:
        if hit.get("rows"):
            return _fmt([(r[0], r[1]) for r in hit["rows"]], stale=True)
        return "（danbooru 查询失败；请用你已知的官方名继续，不要编造）"

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
