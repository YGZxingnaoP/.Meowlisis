# -*- coding: utf-8 -*-
# func/toolbox/napcat/message/time_split.py
# QQ 短期记忆时间分段：按距今时长分层插入会话分割标记

from typing import List

GAP_SECONDS = 6 * 3600
MARK_KEY = "_qq_time_split"


def tier_of(ts: int, now: int) -> int:
    """返回距今时长所在层级（小时）：0/6/12/24/48…"""
    age = max(0, int(now) - int(ts or 0))
    tier, step = 0, 6
    while age >= step * 3600:
        tier, step = step, step * 2
    return tier


def make_marker(tier: int) -> dict:
    """生成会话分割标记"""
    return {
        "role": "system",
        "content": f"【会话分割】以上内容发生在 {tier} 小时之前；此后的属于本次对话",
        MARK_KEY: True,
    }


def is_marker(msg: dict) -> bool:
    """判断是否为时间分段标记"""
    return bool((msg or {}).get(MARK_KEY))


def build_markers(segments: List[dict]) -> List[dict]:
    """按层级插入会话分割标记并清理内部字段"""
    out: List[dict] = []
    prev_tier = None
    for seg in segments:
        tier = int(seg.get("_tier") or 0)
        if prev_tier is not None and prev_tier > 0 and tier < prev_tier:
            out.append(make_marker(prev_tier))
        out.append({"role": seg["role"], "content": seg["content"]})
        prev_tier = tier
    # 整段历史都较旧时末尾补一次，避免模型把昨天的话当成刚刚说的
    if prev_tier:
        out.append(make_marker(prev_tier))
    return out
