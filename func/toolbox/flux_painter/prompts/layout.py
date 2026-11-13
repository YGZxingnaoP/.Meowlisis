# -*- coding: utf-8 -*-
"""官方 Layout JSON 校验/归一（主项目 + 插件共用同一套规则，各自实现一份，互不引用）。

依据 `.vendor/.ComfyNode/node/MOSS-Image-SFT.json` 的「主体提示词」节点：
    {"summary": {"canvas": "single|multi_panel", "caption": "<整段散文>"},   # 可选 meta/...
     "items": [{"label": "character|object|text", "caption": "...",
                "text": "...(仅 text)", "bbox": [y1, x1, y2, x2]}, ...],
     "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"}

规则：
  · 只保留官方字段；label 必须合法；text 项必须带 text；
  · bbox 必须是 4 个整数、yxyx 升序，并夹进画布（中心原点，x∈±W/2、y∈±H/2）；
  · 无法修复的 item 直接丢弃；没有合法 item 就返回 None（调用方退回散文）。
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
