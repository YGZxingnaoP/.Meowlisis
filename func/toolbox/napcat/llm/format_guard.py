# -*- coding: utf-8 -*-
# func/toolbox/napcat/llm/format_guard.py
# QQ 严肃回复格式守卫：检测/剥离 markdown、序号与模板话，并按句截断

import re

_MD_RULES = (
    ("标题", re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+\S")),
    ("加粗", re.compile(r"\*\*[^*\n]+\*\*")),
    ("加粗", re.compile(r"__[^_\n]+__")),
    ("斜体", re.compile(r"(?<!\*)\*[^*\n]+\*(?!\*)")),
    ("删除线", re.compile(r"~~[^~\n]+~~")),
    ("行内代码", re.compile(r"`[^`\n]+`")),
    ("代码块", re.compile(r"```")),
    ("引用", re.compile(r"(?m)^[ \t]{0,3}>[ \t]?\S")),
    ("列表", re.compile(r"(?m)^[ \t]{0,3}[-*+][ \t]+\S")),
    ("序号", re.compile(r"(?m)^[ \t]{0,3}\d{1,2}[.、)][ \t]*\S")),
    ("序号", re.compile(r"(?m)^[ \t]{0,3}[一二三四五六七八九十]+[、.][ \t]*\S")),
    ("表格", re.compile(r"(?m)^[ \t]*\|.*\|[ \t]*$")),
    ("链接", re.compile(r"\[[^\]\n]+\]\([^)\n]+\)")),
    ("分隔线", re.compile(r"(?m)^[ \t]*([-*_])\1{2,}[ \t]*$")),
)

_TEMPLATE_RE = re.compile(
    r"(?:^|[。！？!?\n])\s*(?:首先|其次|再次|最后|总之|总而言之|综上所述|总的来说|"
    r"值得注意的是|需要注意的是|换句话说)\s*[，,、：:]?")
_TEMPLATE_ANY = ("希望对你有帮助",)


def markdown_reasons(text: str) -> list:
    """返回命中的 markdown 类型（去重保序）"""
    body = str(text or "")
    if not body:
        return []
    hits = []
    for label, pattern in _MD_RULES:
        if pattern.search(body) and label not in hits:
            hits.append(label)
    return hits


def has_markdown(text: str) -> bool:
    return bool(markdown_reasons(text))


def has_template(text: str) -> bool:
    body = str(text or "")
    if not body:
        return False
    if _TEMPLATE_RE.search(body):
        return True
    return any(word in body for word in _TEMPLATE_ANY)


def serious_reasons(text: str, limit: int) -> list:
    """严肃回复的驳回原因（markdown / 模板 / 超长）"""
    body = str(text or "")
    reasons = []
    md = markdown_reasons(body)
    if md:
        reasons.append("包含 markdown：" + "、".join(md))
    if has_template(body):
        reasons.append("包含模板化或序号化表达")
    if len(body) > int(limit):
        reasons.append(f"超过 {int(limit)} 字")
    return reasons


def strip_markdown(text: str) -> str:
    """把 markdown 还原为纯文本（只保留内容，不保留标记）"""
    s = str(text or "")
    if not s:
        return s
    s = re.sub(r"```[a-zA-Z0-9_+-]*[ \t]*\n?", "", s)
    s = re.sub(r"~~~[a-zA-Z0-9_+-]*[ \t]*\n?", "", s)
    s = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]*", "", s)
    s = re.sub(r"(?m)^[ \t]{0,3}>[ \t]?", "", s)
    s = re.sub(r"(?m)^[ \t]{0,3}[-*+][ \t]+", "", s)
    s = re.sub(r"(?m)^[ \t]{0,3}\d{1,2}[.、)][ \t]*", "", s)
    s = re.sub(r"(?m)^[ \t]{0,3}[一二三四五六七八九十]+[、.][ \t]*", "", s)
    s = re.sub(r"(?m)^[ \t]*\|?[ \t:|-]+\|[ \t]*$", "", s)
    s = re.sub(r"(?m)^[ \t]*\|(.*)\|[ \t]*$",
               lambda m: m.group(1).replace("|", "、").strip(), s)
    s = re.sub(r"!\[([^\]\n]*)\]\([^)\n]+\)", r"\1", s)
    s = re.sub(r"\[([^\]\n]+)\]\([^)\n]+\)", r"\1", s)
    s = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", s)
    s = re.sub(r"__([^_\n]+)__", r"\1", s)
    s = re.sub(r"~~([^~\n]+)~~", r"\1", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", s)
    s = re.sub(r"`([^`\n]+)`", r"\1", s)
    s = re.sub(r"(?m)^[ \t]*([-*_])\1{2,}[ \t]*$", "", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def strip_template(text: str) -> str:
    """去掉句首模板连接词与固定套话"""
    s = str(text or "")
    if not s:
        return s

    def _drop(match):
        head = match.group(0)[:1]
        return head if head in "。！？!?\n" else ""

    s = _TEMPLATE_RE.sub(_drop, s)
    for word in _TEMPLATE_ANY:
        s = s.replace(word, "")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def truncate_at_sentence(text: str, limit: int) -> str:
    """超长时在 limit 内最后一个句号/换行处截断；找不到就硬截"""
    s = str(text or "").strip()
    limit = int(limit)
    if limit <= 0 or len(s) <= limit:
        return s
    head = s[:limit]
    pos = max(head.rfind("。"), head.rfind("\n"))
    if pos >= max(8, limit // 3):
        return head[:pos + 1].rstrip()
    return head.rstrip()


def clean_serious(text: str, limit: int) -> str:
    """兜底清洗：剥 markdown → 去模板 → 按句截断"""
    return truncate_at_sentence(strip_template(strip_markdown(text)), limit)
