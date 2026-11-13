# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/prompts/danbooru_tool.py
# danbooru 角色 tag 查询工具：交给 LLM 自己调，而不是代码里猜关键词。
#
# 为什么是工具：模型知道角色，但 tag 写法（`shiroko (blue archive)` / `chiz (nte)`）
# 必须查准；把「查」这一步交给 LLM 决定何时查、查什么，比在代码里硬编码关键词可靠。
import json
import urllib.parse
import urllib.request

API = "https://danbooru.donmai.us/tags.json"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
      "Accept": "application/json"}

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


def run(args, config=None, log=None, timeout=None):
    """执行查询，返回喂回给 LLM 的文本（失败也只返回说明，不抛异常）"""
    args = args or {}
    q = str(args.get("query") or "").strip()
    series = str(args.get("series") or "").strip().lower()
    if not q:
        return "（缺少 query：请给出角色英文名）"
    if config is not None and not getattr(config, "danbooru_lookup", True):
        return "（danbooru 查询已关闭，请直接使用你已知的角色名）"
    timeout = timeout or max(3, int(getattr(config, "danbooru_timeout", 8) or 8))

    url = API + "?" + urllib.parse.urlencode({
        "search[name_matches]": "%s*" % q.replace("_", " "),
        "search[order]": "count",
        "limit": 20,
    })
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        if log:
            log.info("[flux_painter] danbooru 工具查询失败: %s" % type(e).__name__)
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
    lines = ["danbooru 候选（按图片数排序，tag 请照抄，括注保留）："]
    for count, name in rows[:8]:
        lines.append("- %s（%d 张）" % (name, count))
    if log:
        log.info("[flux_painter] danbooru 工具命中 %d 条：%s" % (len(rows), rows[0][1]))
    return "\n".join(lines)
