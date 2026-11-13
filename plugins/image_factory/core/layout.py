# -*- coding: utf-8 -*-
"""官方 Layout JSON 校验/归一（插件自包含版，规则与主项目 prompts/layout.py 一致）。

依据 `.vendor/.ComfyNode/node/MOSS-Image-SFT.json`：
    {"summary": {"canvas": "single|multi_panel", "caption": "..."},
     "items": [{"label": "character|object|text", "caption": "...", "text": "...", "bbox": [y1,x1,y2,x2]}],
     "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"}
"""

import json

LABELS = ("character", "object", "text")
CANVASES = ("single", "multi_panel")


def normalize_layout(raw, width=1024, height=1024):
    """吃字符串或 dict，吐压缩后的官方 JSON 字符串；不合法返回 None"""
    obj = raw
    if isinstance(raw, str):
        s = str(raw or "").strip()
        if not s:
            return None
        try:
            obj = json.loads(s)
        except Exception:
            return None
    if not isinstance(obj, dict):
        return None

    summary = obj.get("summary")
    if not isinstance(summary, dict):
        return None
    canvas = str(summary.get("canvas") or "single").strip().lower()
    if canvas not in CANVASES:
        canvas = "single"
    clean_summary = {"canvas": canvas,
                     "caption": str(summary.get("caption") or "").strip()}
    if isinstance(summary.get("meta"), list):
        meta = [str(x).strip() for x in summary["meta"] if str(x).strip()]
        if meta:
            clean_summary["meta"] = meta

    half_w, half_h = int(width) // 2, int(height) // 2
    items = []
    for item in (obj.get("items") or []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip().lower()
        if label not in LABELS:
            continue
        caption = str(item.get("caption") or "").strip()
        if not caption:
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            y1, x1, y2, x2 = [int(round(float(v))) for v in bbox]
        except (TypeError, ValueError):
            continue
        if y1 > y2:
            y1, y2 = y2, y1
        if x1 > x2:
            x1, x2 = x2, x1
        y1, y2 = max(-half_h, min(half_h, y1)), max(-half_h, min(half_h, y2))
        x1, x2 = max(-half_w, min(half_w, x1)), max(-half_w, min(half_w, x2))
        if y2 - y1 < 8 or x2 - x1 < 8:
            continue
        clean = {"label": label, "caption": caption[:600], "bbox": [y1, x1, y2, x2]}
        if label == "text":
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            clean["text"] = text[:200]
        items.append(clean)

    if not items:
        return None
    clean_obj = {"summary": clean_summary, "items": items,
                 "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"}
    return json.dumps(clean_obj, ensure_ascii=False, separators=(",", ":"))
