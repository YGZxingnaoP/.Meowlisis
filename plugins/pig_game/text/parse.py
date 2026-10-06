# -*- coding: utf-8 -*-
"""养猪游戏：指令解析 / 容错 / 别名 / 数量与编队解析。"""

import re

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "两": 2, "贰": 2, "三": 3, "叁": 3,
              "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6, "七": 7, "柒": 7,
              "八": 8, "捌": 8, "九": 9, "玖": 9}
_CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}


def normalize(text):
    """全角转半角、去空格、统一标点。"""
    t = str(text or "")
    out = []
    for ch in t:
        code = ord(ch)
        if code == 0x3000:
            ch = " "
        elif 0xFF01 <= code <= 0xFF5E:
            ch = chr(code - 0xFEE0)
        out.append(ch)
    t = "".join(out)
    t = t.replace("，", ",").replace("、", ",").replace("；", ";").replace("：", ":")
    t = re.sub(r"\s+", "", t)
    return t


def to_int(text):
    """中文数字 / 阿拉伯数字 → int；失败返回 None。"""
    s = str(text or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{1,6}", s):
        return int(s)
    if not all(c in _CN_DIGITS or c in _CN_UNITS for c in s):
        return None
    total, cur, has = 0, 0, False
    for c in s:
        if c in _CN_DIGITS:
            cur = _CN_DIGITS[c]
            has = True
        else:
            unit = _CN_UNITS[c]
            if cur == 0:
                cur = 1
            total += cur * unit
            cur = 0
            has = True
    if not has:
        return None
    return total + cur


_NUM = r"(\d{1,6}|[零〇一壹二两贰三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟]{1,6})"


def parse_squad(book, text):
    """解析编队文本 → {species_id: count}。

    支持「2只神奇飞猪1只鱼猪」「神奇飞猪2只 鱼猪1只」等写法。
    """
    t = normalize(text)
    if not t:
        return {}
    out = {}
    for sp in book.all():
        sid = str(sp["id"])
        names = [sp["name"]] + [str(a) for a in (sp.get("aliases") or [])]
        hit = None
        for nm in names:
            nm = re.escape(nm)
            m = re.search(_NUM + r"只?" + nm, t)          # 数量在前
            if m:
                hit = int(m.group(1)) if m.group(1).isdigit() else to_int(m.group(1))
                break
            m = re.search(nm + r"只?" + _NUM, t)          # 数量在后
            if m:
                hit = int(m.group(1)) if m.group(1).isdigit() else to_int(m.group(1))
                break
        if hit:
            out[sid] = out.get(sid, 0) + int(hit)
    return out


def extract_int(text, default=None):
    """从任意文本里抠出第一个数字（阿拉伯或中文），失败返回 default。"""
    if text is None:
        return default
    if isinstance(text, bool):
        return default
    if isinstance(text, int):
        return text
    if isinstance(text, float):
        return int(text)
    s = normalize(text)
    m = re.search(r"\d{1,6}", s)
    if m:
        return int(m.group(0))
    m = re.search(r"[零〇一壹二两贰三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟]{1,6}", s)
    if m:
        v = to_int(m.group(0))
        if v is not None:
            return v
    return default


def squad_text(book, squad):
    """{species_id: count} → 「2只神奇飞猪、1只鱼猪」"""
    parts = []
    for sid, cnt in (squad or {}).items():
        if int(cnt) > 0:
            parts.append(f"{int(cnt)}只{book.name(sid)}")
    return "、".join(parts)


def pigs_text(book, pigs):
    """猪圈概览文本（数量为 0 的不显示）。"""
    parts = []
    for sp in book.all():
        n = int((pigs or {}).get(str(sp["id"]), 0) or 0)
        if n > 0:
            parts.append(f"{sp['name']}×{n}")
    return " ｜ ".join(parts) if parts else "（空）"


def total_pigs(pigs):
    return sum(int(v or 0) for v in (pigs or {}).values())


def clean_name(text):
    """去掉昵称里的 @ 前缀与空白。"""
    t = str(text or "").strip()
    t = t.lstrip("@").strip()
    return t


def has_prefix(text, prefixes):
    """消息里是否带上了养猪游戏指令前缀。

    拿不到原文（空串）时放行，避免误拦。
    """
    t = normalize(text)
    if not t:
        return True
    for p in (prefixes or []):
        p = normalize(p)
        if p and p in t:
            return True
    return False
