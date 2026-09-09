# -*- coding: utf-8 -*-
# func/toolbox/svg_painter/board.py
# SVG 画布状态：单画板内存态，负责片段安全过滤、追加/整幅替换、输出完整 svg

import re
import threading

from func.log.default_log import DefaultLog


class TBSvgBoardState:
    """全局单画板：
    - fragments: [{'frag_id', 'html', 'time'}]（按作画顺序，html 为 <svg> 内部内容片段）
    - 通过 to_svg() 拼出带 xmlns/viewBox/背景的完整 svg 文本
    - 片段做轻量安全校验（标签白名单 / 去脚本事件 / 长度限制），不引入重型解析库
    """

    # 允许的顶层 SVG 标签白名单（来自 prompts 的 ALLOWED_TAGS）
    ALLOWED_TAGS = (
        "svg", "g", "defs", "linearGradient", "radialGradient", "stop",
        "pattern", "clipPath", "mask", "path", "rect", "circle", "ellipse",
        "line", "polyline", "polygon", "text", "tspan", "use", "title", "desc",
    )

    # 参与定位/布局的关键属性（供 element_index 提取给模型做坐标参照）
    ELEMENT_ATTRS = (
        "x", "y", "cx", "cy", "r", "rx", "ry", "x1", "y1", "x2", "y2",
        "width", "height", "points", "d", "fill", "stroke", "stroke-width",
        "transform", "opacity", "font-size", "text-anchor",
    )

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.Lock()
        self.width = 600
        self.height = 800
        self.bg = "none"          # 默认透明底（画板卡片浅色兜底；需要时 AI 自己铺场景底色）
        self.fragments = []
        self._seq = 0

    # ==================== 基础 ====================
    def reset(self, width: int = 600, height: int = 800, bg: str = "none"):
        """清空画布并设置新规格（新画 / 整幅重构前调用）"""
        with self._lock:
            self.width = max(64, int(width or 600))
            self.height = max(64, int(height or 800))
            self.bg = bg or "none"
            self.fragments = []
            self._seq = 0

    @property
    def fragment_count(self) -> int:
        return len(self.fragments)

    # ==================== 片段安全过滤 ====================
    @classmethod
    def sanitize(cls, raw: str, max_chars: int = 6000) -> str:
        """对模型给出的 SVG 片段做安全过滤与轻校验：
        1. 去掉 <svg> 外层包裹（仅保留内部内容）
        2. 移除 script、事件属性、javascript: 等危险内容
        3. 标签白名单检查（非法标签直接剔除该标签块）
        4. 长度限制（0 = 不限）
        """
        text = (raw or "").strip()
        if not text:
            return ""
        # 去掉外层 <svg ...> ... </svg>（若模型误带包裹）
        m = re.search(r"<svg[\s>]", text, re.IGNORECASE)
        if m:
            end = re.search(r"</svg\s*>", text, re.IGNORECASE)
            inner = text[m.end(): end.start() if end else len(text)]
            text = inner.strip()
        # 删除注释
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        # 删除 <script>...</script>
        text = re.sub(r"<script[\s\S]*?</script\s*>", "", text, flags=re.IGNORECASE)
        # 删除事件属性 onXxx="..."
        text = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", text, flags=re.IGNORECASE)
        # 只移除「外部/危险」引用（http/https/data/javascript），保留 #id 内部引用（use/渐变指向）
        text = re.sub(
            r"(xlink:)?href\s*=\s*(['\"])(?:https?://|data:|javascript:)[^'\"]*\2",
            "", text, flags=re.IGNORECASE
        )
        text = re.sub(r"javascript\s*:", "", text, flags=re.IGNORECASE)

        text = re.sub(r"<\?.*?\?>", "", text, flags=re.DOTALL)          # 处理指令（如 <?xml?>）
        text = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.IGNORECASE)  # DOCTYPE
        text = re.sub(r"<!\[CDATA\[|\]\]>", "", text)                  # CDATA 标记

        # 剔除不在白名单内的非空标签块（保留文本节点与自闭合白名单标签）
        def _strip_bad(match):
            tag = match.group(1).lower()
            return "" if tag not in cls.ALLOWED_TAGS else match.group(0)

        text = re.sub(r"<([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*>", _strip_bad, text)
        text = re.sub(r"</([a-zA-Z][a-zA-Z0-9-]*)\s*>", _strip_bad, text)

        # 长度限制：截断到最后一个完整标签边界，避免切在标签中间产生非法 XML
        if max_chars and max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars]
            cut = text.rfind(">")
            text = text[:cut + 1] if cut > 0 else ""
        # 标签平衡：剔除多余/错序闭合、丢弃孤立结束标签、按栈补齐未闭合，
        # 保证输出片段拼进 <svg> 后是合法 XML（浏览器直接打开不报 mismatch）
        text = cls._balance_tags(text)
        return text.strip()

    @classmethod
    def _balance_tags(cls, text: str) -> str:
        """标签平衡器：把文本里出现过的 SVG 标签整理成严格合法嵌套。

        - 保留白名单标签与其原文属性；
        - 开标签压栈；自闭合标签原样输出；
        - 结束标签必须与栈顶匹配才输出，否则视为多余/错序直接丢弃
          （杜绝孤立 </g> 造成的 "mismatch: svg and g"）；
        - 结尾把栈内未闭合标签按逆序补齐。
        """
        if not text:
            return ""
        out = []
        stack = []  # 已打开的标签名（自闭合不入栈）
        pos = 0
        pattern = re.compile(r"<(/)?\s*([a-zA-Z][a-zA-Z0-9-]*)\b([^>]*?)(/?)>")
        for m in pattern.finditer(text):
            out.append(text[pos:m.start()])   # 标签间的普通文本原样保留
            closing = m.group(1)
            tag = (m.group(2) or "").lower()
            attrs = m.group(3) or ""
            self_close = m.group(4)
            pos = m.end()
            if not tag or tag not in cls.ALLOWED_TAGS:
                continue    # 白名单外的标签整体丢弃（_strip_bad 已删块，这里兜底删标签本身）
            if closing:
                if stack and stack[-1] == tag:
                    stack.pop()
                    out.append(f"</{tag}>")
                # 栈空/栈顶不匹配的结束标签：丢弃，避免 XML mismatch
            elif self_close:
                out.append(f"<{tag}{attrs}/>")
            else:
                stack.append(tag)
                out.append(f"<{tag}{attrs}>")
        out.append(text[pos:])
        for tag in reversed(stack):
            out.append(f"</{tag}>")
        return "".join(out)

    # ==================== 内容操作 ====================
    def append(self, raw_fragments, max_chars: int = 6000):
        """追加一批片段，返回 [{'frag_id', 'html'}, ...]（已过滤/分配 id）"""
        added = []
        if isinstance(raw_fragments, str):
            raw_fragments = [raw_fragments]
        with self._lock:
            for frag in raw_fragments or []:
                html = self.sanitize(str(frag), max_chars)
                if not html:
                    continue
                self._seq += 1
                fid = f"f{self._seq:04d}"
                self.fragments.append({"frag_id": fid, "html": html})
                added.append({"frag_id": fid, "html": html})
        return added

    def load_base(self, full_svg: str, max_chars: int = 6000):
        """载入旧画（整幅 svg 文本）作为画布 base：尺寸继承旧画，内容成为 base 片段"""
        text = (full_svg or "").strip()
        if not text:
            return False
        w = re.search(r"\bwidth\s*=\s*[\"'](\d+)[\"']", text)
        h = re.search(r"\bheight\s*=\s*[\"'](\d+)[\"']", text)
        new_w = int(w.group(1)) if w else 800
        new_h = int(h.group(1)) if h else 600
        # 保留当前画布底色设置（默认 none 透明），仅继承旧画尺寸
        self.reset(new_w, new_h, self.bg)
        with self._lock:
            html = self.sanitize(text, max_chars)
            if not html:
                return False
            self._seq += 1
            self.fragments.append({"frag_id": "base", "html": html})
        return True

    def replace_snapshot(self, raw_svg: str, max_chars: int = 0):
        """整幅替换画布内容（重绘/大改），返回是否成功；成功返回新 frag_id"""
        with self._lock:
            html = self.sanitize(raw_svg, max_chars=max_chars or 20000)
            if not html:
                return None
            self._seq += 1
            fid = f"s{self._seq:04d}"
            self.fragments = [{"frag_id": fid, "html": html}]
            return fid

    # ==================== 输出 ====================
    def to_svg(self) -> str:
        """拼出当前画布完整 svg 文本"""
        with self._lock:
            bg = f'<rect x="0" y="0" width="{self.width}" height="{self.height}" fill="{self.bg}"/>' \
                if self.bg and self.bg.lower() not in ("none", "transparent") else ""
            inner = "".join(f["html"] for f in self.fragments)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}">'
            f"{bg}{inner}</svg>"
        )

    def summary(self) -> str:
        """给模型的画布概要（不传全文，控制 token）"""
        with self._lock:
            lines = [f"当前画布 {self.width}×{self.height}，已有 {len(self.fragments)} 个片段："]
            for f in self.fragments:
                first = re.match(r"<([a-zA-Z][a-zA-Z0-9-]*)\b", f["html"])
                tag = first.group(1) if first else "?"
                lines.append(f"- {f['frag_id']}（{tag}，约 {len(f['html'])} 字符）")
        return "\n".join(lines)

    def element_index(self, limit: int = 1000) -> str:
        """生成紧凑的「画布元素坐标索引」：逐片段提取关键元素的定位/尺寸/配色属性，
        供绘画模型在落笔前参照已有元素坐标，避免分步作画时重叠、错位、乱定位。

        仅提取定位相关属性（x/cx/r/d/points/transform/fill 等），不传整段 SVG，控制 token。
        """
        with self._lock:
            frags = list(self.fragments)
        if not frags:
            return ""
        lines = []
        tag_pat = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)\b([^>]*)>")
        attr_pat = re.compile(r"""([a-zA-Z-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
        # 仅承载定义、不含画面元素定位意义的标签
        skip_tags = {"svg", "defs", "linearGradient", "radialGradient", "stop",
                     "pattern", "clipPath", "mask", "title", "desc"}
        total = 0
        for f in frags:
            fid = f["frag_id"]
            html = f["html"]
            parts = []
            for tm in tag_pat.finditer(html):
                tag = tm.group(1).lower()
                if tag in skip_tags or tag not in self.ALLOWED_TAGS:
                    continue
                body = tm.group(2) or ""
                kv = []
                for a in attr_pat.finditer(body):
                    name = a.group(1).lower()
                    if name not in self.ELEMENT_ATTRS:
                        continue
                    val = (a.group(2) or a.group(3) or "").strip()
                    if not val:
                        continue
                    if name in ("d", "points") and len(val) > 48:
                        val = val[:48] + "…"
                    kv.append(f"{name}={val}")
                if kv:
                    parts.append(f"<{tag} {' '.join(kv)}>")
                if len(parts) >= 6:
                    break
            if not parts:
                continue
            seg = " · ".join(parts)
            lines.append(f"{fid}: {seg[:320]}")
            total += len(lines[-1])
            if total >= limit:
                break
        return "\n".join(lines)
