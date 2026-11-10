# -*- coding: utf-8 -*-
# func/toolbox/napcat/llm/narration/contrast.py
# 对比句改写：不是A而是B / 不是A是B -> 是B；是A不是B -> 就是A吧，和B不一样。

import re

_SENT_SPLIT = re.compile(r"(?<=[。！？!?\n])")
_NOT_BUT = re.compile(r"(?<!是)(?:并不是|不是).*?而是", re.S)
_NOT_IS = re.compile(r"(?<!是)(?:并不是|不是).*?是", re.S)
_WEIBI_IS = re.compile(r"未必是(?P<a>.+?)(?:，|,)?\s*是(?P<b>.+)$", re.S)
_IS_WEIBI = re.compile(r"未必是(?P<b>.+)$", re.S)
_COMPARE = re.compile(
    r"(?P<pre>.*?)(?<!比)比(?P<x>.{1,40}?)(?:还|更|都)?"
    r"(?P<y>狠|重|轻|稳|平|强|直)(?!一些|一点)", re.S)
_BAD_COPULA_PREFIX = re.compile(r"(?<![这那可但还就正也都只不而])是")
_TRAIL = "。！？!?"
_TIME = {"之前", "刚才", "以前", "上回", "平时", "平常", "以往"}
_COMPARE_MAP = {
    "狠": "真有说法",
    "重": "好有感觉",
    "轻": "好舒服",
    "稳": "好靠谱",
    "平": "好顺",
    "强": "好厉害",
    "直": "好直接",
}


def _rewrite_not_but(s: str) -> str:
    for _ in range(2):
        m = _NOT_BUT.search(s)
        if not m:
            break
        b = s[m.end():]
        if not b.strip():
            break
        s = s[:m.start()] + "是" + b
    return s


def _rewrite_not_is(s: str) -> str:
    m = _NOT_IS.search(s)
    if not m:
        return s
    b = s[m.end():]
    if not b.strip():
        return s
    return s[:m.start()] + "是" + b


def _rewrite_weibi_is(s: str) -> str:
    m = _WEIBI_IS.search(s)
    if not m:
        return s
    return f"未必是{m.group('a').strip()}吧，是{m.group('b').strip()}"


def _rewrite_is_weibi(s: str) -> str:
    m = _IS_WEIBI.search(s)
    if not m:
        return s
    before = re.sub(r"[，,、；;\s]+$", "", s[:m.start()])
    cop = None
    for cm in _BAD_COPULA_PREFIX.finditer(before):
        cop = cm
    if cop is None:
        return s
    prefix = before[:cop.start()]
    a = before[cop.end():].strip()
    b = m.group("b").strip()
    if not a or not b:
        return s
    return f"{prefix}就是{a}吧，未必是{b}"


def _rewrite_is_not(s: str) -> str:
    for m in re.finditer(r"(?<!是)不是", s):
        before = re.sub(r"[，,、；;\s]+$", "", s[:m.start()])
        cop = None
        for cm in _BAD_COPULA_PREFIX.finditer(before):
            cop = cm
        if cop is None:
            continue
        prefix = before[:cop.start()]
        a = before[cop.end():].strip()
        a = re.sub(r"的$", "", a).strip()
        b = re.sub(r"^[，,、；;\s]+", "", s[m.end():]).strip()
        b = re.sub(r"^这些", "", b)
        if not a or not b:
            continue
        tail = s[-1] if s and s[-1] in _TRAIL else ""
        b = b.rstrip(_TRAIL).strip()
        if not b:
            continue
        return f"{prefix}就是{a}吧，和{b}不一样{tail}"
    return s


def _rewrite_compare(s: str) -> str:
    m = _COMPARE.search(s)
    if not m:
        return s
    x = m.group("x").strip()
    y = m.group("y")
    if not x or y not in _COMPARE_MAP:
        return s
    pre = m.group("pre")
    suffix = s[m.end():]
    if suffix.startswith("的"):
        noun_raw = suffix[1:].strip()
        tail = noun_raw[-1] if noun_raw and noun_raw[-1] in _TRAIL else ""
        noun = noun_raw.rstrip(_TRAIL).strip()
        if noun:
            return f"说到{x}，{noun}{_COMPARE_MAP[y]}{tail}"
    if x in _TIME:
        return f"{pre}{_COMPARE_MAP[y]}{suffix}"
    return f"{pre}{x}{_COMPARE_MAP[y]}{suffix}"


def rewrite_contrast(text: str) -> str:
    s = str(text or "")
    if not s:
        return s
    parts = _SENT_SPLIT.split(s)
    out = []
    for part in parts:
        if part:
            if "是不是" in part or re.search(r"不是.*吗[？?]?$", part.strip()):
                out.append(part)
                continue
            part = _rewrite_not_but(part)
            part = _rewrite_not_is(part)
            part = _rewrite_weibi_is(part)
            part = _rewrite_is_weibi(part)
            part = _rewrite_is_not(part)
            part = _rewrite_compare(part)
        out.append(part)
    return "".join(out)
