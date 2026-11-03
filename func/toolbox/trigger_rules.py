# -*- coding: utf-8 -*-
# func/toolbox/trigger_rules.py
# 父级触发规则协议：工具模块自己声明「什么话 → 用哪个工具」，父级只负责匹配与执行
#
# 两种模式（父级各有一份通用执行器，不在父级写任何具体工具逻辑）：
#   forced —— 命中即用指定入口执行（参数由 args(text) 生成），如看屏幕 / 画图；
#   choose —— 命中后让角色在 candidates 里选一个入口再执行，如「qq发消息」时
#             在 napcat_send（发消息/@人）和 napcat_ask_bot（指挥幻梦）之间选。

FORCED = "forced"
CHOOSE = "choose"


def _words(words) -> tuple:
    return tuple(str(w) for w in (words or ()) if str(w).strip())


def forced(tool: str, words, args=None) -> dict:
    """命中关键词就用 tool 这个入口执行

    :param args: 由原文生成参数；缺省 {"request": text}
    """
    return {"mode": FORCED, "tool": str(tool), "words": _words(words),
            "args": args or (lambda text: {"request": text})}


def choose(candidates, words, prompt: str, hint=None,
           fallback: str = "", speak_result: bool = False) -> dict:
    """命中关键词后让角色在 candidates 里选一个入口执行

    :param prompt:       选择器的系统提示词（写清每个候选是干什么的、怎么选）
    :param hint:         可选；字符串或 callable，追加到提示词（真实群名、@ 规则等）
    :param fallback:     模型选不出来时兜底用的入口（保证必然触发）
    :param speak_result: 执行完是否让角色把结果说出来（这类工具自己不出声）
    """
    return {"mode": CHOOSE, "candidates": tuple(candidates), "words": _words(words),
            "prompt": str(prompt or ""), "hint": hint,
            "fallback": str(fallback or ""), "speak_result": bool(speak_result)}


def matched(rule: dict, text: str) -> bool:
    """规则关键词是否命中（大小写不敏感）"""
    body = str(text or "").lower()
    return bool(body) and any(w.lower() in body for w in rule.get("words") or ())
