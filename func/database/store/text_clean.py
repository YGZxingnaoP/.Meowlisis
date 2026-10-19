# -*- coding: utf-8 -*-
# func/database/store/text_clean.py
# 入库前的文本准备：只做「去掉我们自己写的东西」和「按标题分段」，不猜内容
#
# 设计原则（经全量数据验证后确定）：
#   1. 不删正文。任何「猜这一段是不是垃圾」的规则都会误删有效内容——
#      实测「碎片块」规则会删掉 CAST 声优表、角色描写、歌词；
#      「跨文档频次」规则会删掉曲目名、片头曲(OP)/片尾曲(ED) 这类常用词。
#   2. 只删除按构造可知的东西：入库器自己写的段标题（INJECTED_SECTIONS）。
#   3. 表格分隔行（|:---|---:|）是纯标记，无信息量，删除。
#   4. 标题是结构，不是噪音：标题原文保留，作为「小节」的边界与每个 chunk 的前缀。
#      不分类、不映射、不查词表——标题原文本身就是语义载荷
#      （CAST / STAFF / 登场角色 的语义由 embedding 自己理解）。
#   5. 数据事实：全库 457 个去重小节名，75% 只出现 1 篇；38% 的文档没有任何标题。
#      因此任何「词表/分类」方案必然漏，只能按「有没有标题」走两条路。
#
# 对外入口：
#   build_units(text, doc_name, chunker, ...) -> list[dict]
#       把一篇正文变成若干「带小节信息」的入库单元，每单元对应一个向量。
#
# 产出单元的 metadata 字段：section / section_index / chunk_index / chunk_total

import re

# ---- 自有格式约定：入库器自己写进去的段，按构造删除 ----
INJECTED_SECTIONS = ("## 我的记录",)      # 整段删除
SCAFFOLD_LINES = ("## 萌娘百科条目",)      # 只删标题行，正文保留

# 单个入库单元的最小正文字数（不含前缀）
MIN_UNIT_CHARS = 10

# 标题语法：wiki(== x ==) 与 markdown(## x)，两者都在数据中出现过
_HEAD_EQ = re.compile(r"^\s*(={2,6})\s*(.+?)\s*\1\s*$")
_HEAD_HASH = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
# 表格分隔行：| --- | --- |
_SEP_ROW = re.compile(r"^\s*\|?[\s:|\-]{4,}\|?\s*$")
_WS = re.compile(r"[ \t\u3000]{2,}")


def match_heading(line: str):
    """匹配标题行，返回标题原文；不是标题返回 None

    只认语法形态，不认标题内容——所以任何站点、任何语言的标题都能取到。
    """
    s = line.rstrip()
    m = _HEAD_EQ.match(s)
    if m:
        return m.group(2).strip()
    m = _HEAD_HASH.match(s)
    if m:
        return m.group(2).strip()
    return None


def is_table_separator(line: str) -> bool:
    """表格分隔行（纯标记，无信息量）"""
    s = line.strip()
    if not s:
        return False
    return bool(_SEP_ROW.match(s)) and ("-" in s) and ("|" in s or ":" in s)


def strip_own_scaffold(text: str) -> str:
    """删除入库器自己加的段

    这不是启发式：这些标记是本项目写进去的格式约定，按构造可知。
    """
    out, skipping = [], False
    for ln in str(text or "").splitlines():
        s = ln.strip()
        if s in INJECTED_SECTIONS:
            skipping = True
            continue
        # 遇到下一个标题结束跳过区
        if skipping and (match_heading(ln) is not None or s.startswith("#")):
            skipping = False
        if skipping:
            continue
        if s in SCAFFOLD_LINES:
            continue
        out.append(ln)
    return "\n".join(out)


def drop_table_separators(text: str) -> str:
    """只删表格分隔行，不删表格数据行（数据行是内容）"""
    keep = [ln for ln in str(text or "").splitlines() if not is_table_separator(ln)]
    return "\n".join(keep)


def tidy(text: str) -> str:
    """轻量整理：去行尾空白、压缩连续空行。不改写内容"""
    out, blank = [], 0
    for ln in str(text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = _WS.sub(" ", ln).rstrip()
        if not line:
            blank += 1
            if blank > 2:
                continue
        else:
            blank = 0
        out.append(line)
    return "\n".join(out).strip()


def split_sections(text: str) -> list:
    """按标题把正文切成小节

    Args:
        text: 已去掉自有脚手架的正文。

    Returns:
        list[tuple[str, str]]: [(标题原文, 小节正文)]；首个元素的标题可能是空串
        （文档开头没有标题的部分）。没有标题的文档会得到单个 ("", 全文)。
    """
    sections = []
    cur_head, buf = "", []
    for ln in str(text or "").splitlines():
        head = match_heading(ln)
        if head is not None:
            sections.append((cur_head, "\n".join(buf)))
            cur_head, buf = head, []
        else:
            buf.append(ln)
    sections.append((cur_head, "\n".join(buf)))
    return sections


def segment_body(body: str, chunker, target_tokens: int) -> list:
    """在一个小节内部切块，**保留换行**

    不用 CatLearnChunker.merge_to_chunks，因为它的 split_sentences 对每句做了
    strip()，会把换行符吃掉——列表类内容（CAST 的配音名单、曲目、话数表）
    会被拼成一长串，可读性和语义都会变差。

    这里按行累积到 token 预算；只有单行本身超预算时才退回句级切分。

    Args:
        body: 小节正文。
        chunker: 提供 count_tokens / chunk 的分块器（用于 token 估算与超长行降级）。
        target_tokens: 单块目标 token 数。

    Returns:
        list[str]: 按行边界切出的正文块（可能为空列表）。
    """
    count = getattr(chunker, "count_tokens", None)
    pieces, cur, cur_tok = [], [], 0
    for ln in str(body or "").splitlines():
        ln_tok = count(ln) if count else max(1, int(len(ln) / 2.4))
        if ln_tok > target_tokens:
            # 单行就超预算：先收尾当前块，再对这一行做句级切分
            if cur:
                pieces.append("\n".join(cur))
                cur, cur_tok = [], 0
            pieces.extend(chunker.chunk(ln, target_tokens=target_tokens,
                                        overlap_ratio=0.0) or [])
            continue
        if cur and cur_tok + ln_tok > target_tokens:
            pieces.append("\n".join(cur))
            cur, cur_tok = [], 0
        cur.append(ln)
        cur_tok += ln_tok
    if cur:
        pieces.append("\n".join(cur))
    return [p for p in pieces if p and p.strip()]


def build_units(text: str, doc_name: str, chunker,
                target_tokens: int = 256, overlap_ratio: float = 0.1,
                min_chars: int = MIN_UNIT_CHARS) -> list:
    """把一篇正文变成「带小节信息」的入库单元

    流程：去自有脚手架 → 删表格分隔行 → 按标题分段 → 小节内按行切块 → 加前缀。

    前缀格式：`《文档名》·小节标题（i/n）`，让每个 chunk 自解释，
    检索时不再需要额外的分类标签。

    Args:
        text: 原始正文。
        doc_name: 文档名（用于前缀）。
        chunker: 具备 chunk() / count_tokens() 的分块器。
        target_tokens: 单块目标 token 数。
        overlap_ratio: 保留参数以兼容旧调用；按行切块不使用重叠。
        min_chars: 单元正文的最小字数（不含前缀）。

    Returns:
        list[dict]: [{text, section, section_index, chunk_index, chunk_total}]
    """
    body = tidy(drop_table_separators(strip_own_scaffold(text)))
    if not body:
        return []

    units = []
    for si, (heading, sec_body) in enumerate(split_sections(body)):
        sec_body = sec_body.strip()
        if not sec_body:
            continue
        parts = segment_body(sec_body, chunker, target_tokens)
        if not parts:
            continue
        total = len(parts)
        for ci, part in enumerate(parts, 1):
            part = tidy(part)
            if len(part) < min_chars:
                continue
            head = f"《{doc_name}》" if doc_name else ""
            if heading:
                head = f"{head}·{heading}" if head else heading
            if total > 1:
                head = f"{head}（{ci}/{total}）" if head else f"（{ci}/{total}）"
            units.append({
                "text": f"{head}\n{part}" if head else part,
                "section": heading,
                "section_index": si,
                "chunk_index": ci,
                "chunk_total": total,
            })
    return units
