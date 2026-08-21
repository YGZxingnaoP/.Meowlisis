# -*- coding: utf-8 -*-
# func/tools/smart_snippet.py
# 智能截断：按完整句子边界截取，保证内容精简但完整（不切断句子/词语）

import re


def _normalize(text: str) -> str:
    """压缩空白：把连续空白/换行压成单个空格或换行"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 连续换行 -> 单个换行（保留列表换行结构）
    text = re.sub(r"\n{2,}", "\n", text)
    # 行内连续空白 -> 单个空格
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.split("\n")]
    # 去掉空行
    return "\n".join([l for l in lines if l])


def smart_snippet(text: str, max_len: int, suffix: str = "…") -> str:
    """按句子边界智能截断，返回不超过约 max_len 的完整片段。

    规则：
    1. 先压缩空白；
    2. 若原文长度 <= max_len，直接返回原文（不截断）；
    3. 按句末标点（。！？!?；;）和换行切分；
    4. 贪心累加【完整】句子，接近 max_len 即停（宁短勿断）；
    5. 若第一个句子本身就超过 max_len，则硬切到 max_len（兜底）；
    6. 截断时末尾补 suffix 标记。

    max_len <= 0 表示不限制（返回原文）。
    """
    text = _normalize(text)
    if not text or max_len <= 0 or len(text) <= max_len:
        return text

    # 按句末标点、逗号或换行切分，分隔符保留在单元末尾（换行得以保留）
    units = re.split(r"(?<=[。！？!?；;，,、\n])", text)
    units = [u for u in units if u and u.strip()]

    result = ""
    for unit in units:
        # 当前单元本身超过 max_len：如果还什么都没装，硬切兜底
        if not result and len(unit) > max_len:
            return unit[:max_len].rstrip() + suffix
        # 累加后超长：停止（宁短勿断）
        if len(result) + len(unit) > max_len:
            break
        result += unit
        # 已接近上限就提前结束
        if len(result) >= max_len:
            break

    # 去掉结尾可能残留的标点与空白，再补省略号
    result = result.rstrip("，,、。！？!?；; \t\n")
    if not result:
        return text[:max_len].rstrip() + suffix
    # 只有确实被截短时才补省略号
    if len(result) < len(text):
        return result + suffix
    return result
