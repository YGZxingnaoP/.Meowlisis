# -*- coding: utf-8 -*-
# func/database/search/content_quality.py
# 抓取内容质量门：识别反爬挑战页 / 错误页 / 过短内容，防止污染知识库
#
# 背景：萌娘百科等站点被 Cloudflare 保护，HTML 详情页会返回 403 挑战页
# （正文只有「正在进行安全验证…Enable JavaScript and cookies to continue」），
# 这类内容一旦落盘就会被 learning 分块入库，成为可被检索的垃圾知识。
# 这里提供唯一的判定入口，采集落盘前与入库前各调一次（双保险）。

import re

# 少于该字符数视为无价值内容（挑战页约 90 字）；中日英统一按字符数计
MIN_CHARS = 120

# 反爬 / 验证挑战页特征（统一按小写比较）
CHALLENGE_MARKERS = (
    "正在进行安全验证",
    "本网站使用安全服务",
    "验证您不是自动程序",
    "验证成功。正在等待",
    "enable javascript and cookies",
    "just a moment",
    "checking your browser",
    "challenge-platform",
    "cf-browser-verification",
    "access to this page has been denied",
    "人机验证",
    "滑动验证",
    "访问验证",
)

# 错误页特征
ERROR_MARKERS = (
    "403 forbidden",
    "404 not found",
    "access denied",
    "页面不存在",
    "您访问的页面不存在",
    "该页面无法访问",
    "请求被拒绝",
    "too many requests",
)

# HTML 标签残留：正文提取失败时会整段返回标签
_TAG_RE = re.compile(r"<[a-zA-Z/][^>]{0,200}>")
# 标签数超过该值且占比过高，判定为未提取干净的 HTML
_TAG_COUNT_LIMIT = 8

_WS_RE = re.compile(r"[ \t\u3000]+")


def _normalize(text: str) -> str:
    """压缩空白，便于字数统计与标记匹配"""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    s = _WS_RE.sub(" ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def find_marker(text: str):
    """只做标记匹配（不看字数/标签），返回命中的标记，未命中返回空串。

    与 is_junk 区分：存量清理必须用这个——库里正常的尾部 chunk 可能短于
    MIN_CHARS，用 is_junk 会误删；只有反爬/错误页标记才是确定无疑的垃圾。

    Args:
        text: 待检查文本。

    Returns:
        str: 命中的标记（形如 "反爬挑战页:正在进行安全验证"），未命中为空串。

    """
    low = (text or "").lower()
    if not low:
        return ""
    for marker in CHALLENGE_MARKERS:
        if marker in low:
            return f"反爬挑战页:{marker}"
    for marker in ERROR_MARKERS:
        if marker in low:
            return f"错误页:{marker}"
    return ""


def is_junk(text: str):
    """判断抓取到的正文是否为垃圾内容。

    Args:
        text: 合并后的正文（可能含【标题】前缀，不影响判定）。

    Returns:
        tuple[bool, str]: (是否垃圾, 原因)。非垃圾时原因为空串。

    """
    s = _normalize(text)
    if not s:
        return True, "空内容"

    hit = find_marker(s)
    if hit:
        return True, hit

    if len(s) < MIN_CHARS:
        return True, f"内容过短:{len(s)}字<{MIN_CHARS}"

    tags = _TAG_RE.findall(s)
    if len(tags) >= _TAG_COUNT_LIMIT and len("".join(tags)) / max(1, len(s)) > 0.05:
        return True, f"HTML标签残留:{len(tags)}个"

    return False, ""
