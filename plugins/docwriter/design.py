# -*- coding: utf-8 -*-
"""docwriter 设计系统：配色 / 字号 / 间距 / DOCX 样式表。

设计原则
--------
1. 美观由「代码里的设计令牌 + 版式函数」保证，不靠模型猜坐标；
   模型只负责：用哪个主题、每页用哪个版式、写什么内容。
2. 一套令牌同时供 DOCX 与 PPTX 使用，两种产物视觉一致。
3. 所有颜色用十六进制字符串声明，取用时转成 RGBColor / RGBColor 等。

主题（THEMES）字段
------------------
primary   主色（标题、强调条）
secondary 辅色（次级强调、图表副色）
accent    点缀色（数字、关键字、标签）
ink       正文主色（近黑，不用纯黑，观感更柔和）
muted     次要文字（图注、页码）
line      分隔线
bg        页面底色
soft      浅色块（表格斑马纹、引用块底）
"""

# ==================== 主题 ====================

THEMES = {
    "tech": {
        "name": "科技蓝", "primary": "#1A73E8", "secondary": "#00ACC1", "accent": "#FF6D00",
        "ink": "#202124", "muted": "#5F6368", "line": "#DADCE0", "bg": "#FFFFFF", "soft": "#EFF5FE",
    },
    "business": {
        "name": "商务墨蓝", "primary": "#1F3B57", "secondary": "#3E7CB1", "accent": "#C9A227",
        "ink": "#1C1C1E", "muted": "#6B7280", "line": "#DCDFE4", "bg": "#FFFFFF", "soft": "#F2F5F8",
    },
    "warm": {
        "name": "暖阳橙", "primary": "#E8590C", "secondary": "#F59F00", "accent": "#2B8A3E",
        "ink": "#2B2118", "muted": "#7A6A5A", "line": "#EADFD4", "bg": "#FFFFFF", "soft": "#FFF4EC",
    },
    "forest": {
        "name": "森野绿", "primary": "#2F7A55", "secondary": "#6AA84F", "accent": "#D97706",
        "ink": "#1E2A22", "muted": "#62736A", "line": "#DCE5DE", "bg": "#FFFFFF", "soft": "#EEF6F1",
    },
    "violet": {
        "name": "夜紫", "primary": "#5B3FA8", "secondary": "#8E6FD8", "accent": "#E4572E",
        "ink": "#221C33", "muted": "#6E6685", "line": "#E2DCF0", "bg": "#FFFFFF", "soft": "#F3F0FB",
    },
    "mono": {
        "name": "极简黑白", "primary": "#222222", "secondary": "#666666", "accent": "#C0392B",
        "ink": "#1A1A1A", "muted": "#7A7A7A", "line": "#E0E0E0", "bg": "#FFFFFF", "soft": "#F5F5F5",
    },
}

DEFAULT_THEME = "tech"

# ==================== 字体 ====================

FONT_CN = "微软雅黑"          # Windows 自带，避免中文变方框
FONT_CN_LIGHT = "微软雅黑 Light"
FONT_EN = "Arial"

# ==================== 字号阶梯（pt） ====================

SIZE = {
    "cover_title": 40, "cover_sub": 18, "cover_meta": 12,
    "h1": 26, "h2": 19, "h3": 15, "body": 12, "small": 10.5, "caption": 9.5,
    # PPT 固定字阶（只用这些档位，禁止 +1/-2 这类临时算术，保证全篇字号一致）
    "ppt_no": 68,          # 章节编号
    "ppt_display": 52,     # 数据大卡数字
    "ppt_big": 38,         # 结尾页主句
    "ppt_title": 30,       # 页标题
    "ppt_h2": 18,          # 区块小标题
    "ppt_body": 17,        # 要点正文（基准）
    "ppt_body2": 15,       # 降级一档
    "ppt_small": 13,       # 次级要点 / 卡片内容 / 引用
    "ppt_caption": 11,     # 图注 / 小标签 / 表格正文 / 页脚
    "ppt_quote": 24,       # 金句页
}

# ==================== 间距（cm） ====================

GAP = {"margin": 2.2, "block": 0.9, "line": 0.55}

PAGE = {"ppt_w": 33.867, "ppt_h": 19.05}     # 16:9（cm）

# ==================== 派生色 ====================

PT_PER_CM = 28.3465          # 1cm = 28.35pt
CJK_EM = 1.0                 # 汉字按 1 个字宽 = 1em
ASCII_EM = 0.55              # 英文/数字按 0.55em 估宽

# 字号降级阶梯（一次算完，不做迭代重排）
SIZE_LADDER = (17, 15, 13, 11)
MIN_SIZE = 11

# 圆角/描边图片加工参数
FRAME_RADIUS = 0.02          # 圆角半径 = 短边 × 2%
FRAME_BORDER = 2             # 描边像素
FRAME_CACHE = "_framed"


def tint(color, ratio):
    """与白色混合（ratio=0.08 → 8% 主色的浅底）"""
    r, g, b = hex_rgb(color)
    f = max(0.0, min(1.0, float(ratio)))
    return "#%02X%02X%02X" % (int(r + (255 - r) * (1 - f)),
                              int(g + (255 - g) * (1 - f)),
                              int(b + (255 - b) * (1 - f)))


def shade(color, ratio):
    """与黑色混合"""
    r, g, b = hex_rgb(color)
    f = max(0.0, min(1.0, float(ratio)))
    return "#%02X%02X%02X" % (int(r * (1 - f)), int(g * (1 - f)), int(b * (1 - f)))


def derive(theme):
    """补出派生色：浅底、更浅底、柔和分隔线（版面层次靠它）"""
    th = dict(theme)
    th["tint8"] = tint(theme.get("primary", "#1A73E8"), 0.08)
    th["tint14"] = tint(theme.get("primary", "#1A73E8"), 0.14)
    th["tint_soft"] = tint(theme.get("secondary", "#00ACC1"), 0.10)
    th["line_soft"] = tint(theme.get("muted", "#5F6368"), 0.55)
    th["card"] = tint(theme.get("primary", "#1A73E8"), 0.06)
    return th


def get_theme(key=None):
    """取主题字典（未知 key 回退默认，支持直接传字典）"""
    if isinstance(key, dict):
        base = dict(THEMES[DEFAULT_THEME])
        base.update(key)
        return derive(base)
    return derive(THEMES.get(str(key or DEFAULT_THEME), THEMES[DEFAULT_THEME]))


def theme_names():
    """全部主题（供 GUI 下拉）"""
    return [{"value": k, "label": v["name"]} for k, v in THEMES.items()]


def hex_rgb(value):
    """#RRGGBB → (r, g, b)"""
    s = str(value or "#000000").lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except Exception:
        return 0, 0, 0


def _east_asian(style, font_name):
    """让 Word 样式的中文字体也生效（python-docx 默认只设 latin 字体）"""
    from docx.oxml.ns import qn

    style.font.name = font_name
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)
    rfonts.set(qn("w:ascii"), font_name)
    rfonts.set(qn("w:hAnsi"), font_name)


# ==================== DOCX 样式表 ====================

def apply_docx_theme(doc, theme):
    """把设计令牌写进 Word 样式表（标题层级 / 正文 / 图注 / 引用 / 表格）"""
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Pt, RGBColor

    ink = RGBColor(*hex_rgb(theme["ink"]))
    primary = RGBColor(*hex_rgb(theme["primary"]))
    muted = RGBColor(*hex_rgb(theme["muted"]))

    normal = doc.styles["Normal"]
    _east_asian(normal, FONT_CN)
    normal.font.size = Pt(SIZE["body"])
    normal.font.color.rgb = ink
    pf = normal.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.45
    pf.space_after = Pt(6)

    # 首行缩进 2 字符（中文正文规范）
    try:
        normal.paragraph_format.first_line_indent = Pt(SIZE["body"] * 2)
    except Exception:
        pass

    for name, size, color, before, after in (
        ("Title", SIZE["cover_title"], primary, 0, 12),
        ("Heading 1", SIZE["h1"], primary, 18, 8),
        ("Heading 2", SIZE["h2"], primary, 14, 6),
        ("Heading 3", SIZE["h3"], ink, 12, 4),
    ):
        try:
            st = doc.styles[name]
            _east_asian(st, FONT_CN)
            st.font.size = Pt(size)
            st.font.color.rgb = color
            st.font.bold = True
            st.paragraph_format.space_before = Pt(before)
            st.paragraph_format.space_after = Pt(after)
            st.paragraph_format.first_line_indent = Pt(0)
            st.paragraph_format.line_spacing = 1.25
        except Exception:
            continue

    for name, size, color, italic, bold in (
        ("Caption", SIZE["caption"], muted, False, False),
        ("Quote", SIZE["body"], ink, True, False),
        ("List Bullet", SIZE["body"], ink, False, False),
        ("List Number", SIZE["body"], ink, False, False),
    ):
        try:
            st = doc.styles[name]
            _east_asian(st, FONT_CN)
            st.font.size = Pt(size)
            st.font.color.rgb = color
            st.font.italic = italic
            st.font.bold = bold
            st.paragraph_format.first_line_indent = Pt(0)
            st.paragraph_format.space_after = Pt(4)
        except Exception:
            continue
    try:
        doc.styles["Caption"].paragraph_format.alignment = 1  # 居中图注
    except Exception:
        pass


def docx_cover(doc, theme, title, subtitle="", meta_lines=None):
    """代码生成封面页：色条 + 主标题 + 副标题 + 元信息"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    for _ in range(4):
        doc.add_paragraph()
    bar = doc.add_paragraph()
    bar.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = bar.add_run("━" * 3)                      # 装饰色条（用字符实现，零素材）
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(*hex_rgb(theme["primary"]))
    run.font.bold = True

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run(str(title or "文档"))
    r.font.size = Pt(SIZE["cover_title"])
    r.font.bold = True
    r.font.color.rgb = RGBColor(*hex_rgb(theme["primary"]))
    r.font.name = FONT_CN

    if subtitle:
        s = doc.add_paragraph()
        s.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sr = s.add_run(str(subtitle))
        sr.font.size = Pt(SIZE["cover_sub"])
        sr.font.color.rgb = RGBColor(*hex_rgb(theme["muted"]))

    for line in (meta_lines or []):
        m = doc.add_paragraph()
        m.alignment = WD_ALIGN_PARAGRAPH.CENTER
        mr = m.add_run(str(line))
        mr.font.size = Pt(SIZE["cover_meta"])
        mr.font.color.rgb = RGBColor(*hex_rgb(theme["muted"]))

    doc.add_page_break()


def docx_page_footer(doc, theme, text=""):
    """页脚：主题色细线 + 页码域"""
    try:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor

        section = doc.sections[0]
        p = section.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if text:
            r0 = p.add_run(str(text) + "   ")
            r0.font.size = Pt(SIZE["caption"])
            r0.font.color.rgb = RGBColor(*hex_rgb(theme["muted"]))
        run = p.add_run()
        run.font.size = Pt(SIZE["caption"])
        run.font.color.rgb = RGBColor(*hex_rgb(theme["muted"]))
        fld = run._r.makeelement(qn("w:fldSimple"), {qn("w:instr"): "PAGE"})
        run._r.append(fld)
    except Exception:
        pass


def docx_header(doc, theme, text=""):
    """页眉：文档名 + 主题色细线"""
    try:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt, RGBColor

        p = doc.sections[0].header.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = p.add_run(str(text or ""))
        r.font.size = Pt(SIZE["caption"])
        r.font.color.rgb = RGBColor(*hex_rgb(theme["muted"]))
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        pbdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "4")
        bottom.set(qn("w:color"), hex_rgb_hex(theme["line_soft"]))
        pbdr.append(bottom)
        p._p.get_or_add_pPr().append(pbdr)
    except Exception:
        pass


def hex_rgb_hex(value):
    """#RRGGBB → 不含 # 的 RRGGBB（Word XML 用）"""
    return str(value or "#000000").lstrip("#").upper()[:6]


def docx_toc_field(doc):
    """插入 Word 目录域（打开文档后按 F9 更新）"""
    try:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        p = doc.add_paragraph()
        run = p.add_run()
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = 'TOC \\o "1-3" \\h \\z \\u'
        sep = OxmlElement("w:fldChar")
        sep.set(qn("w:fldCharType"), "separate")
        txt = OxmlElement("w:t")
        txt.text = "（右键此处→更新域，生成目录）"
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        for el in (begin, instr, sep, txt, end):
            run._r.append(el)
        doc.add_page_break()
    except Exception:
        pass


# ==================== 文本度量（一步做对的核心） ====================

def text_em(text):
    """估算文本宽度（单位：em；汉字 1.0，英文数字 0.55）"""
    em = 0.0
    for ch in str(text or ""):
        em += ASCII_EM if ord(ch) < 0x2E80 else CJK_EM
    return em


def fit_size(text, width_cm, base=17, ladder=SIZE_LADDER):
    """在给定宽度内能放下的最大字号（从阶梯取，一次算完）"""
    em = text_em(text)
    if em <= 0:
        return base
    for s in (base,) + tuple(x for x in ladder if x < base):
        if em * s / PT_PER_CM <= width_cm:
            return s
    return MIN_SIZE


def fit_text(text, width_cm, base=17):
    """返回 (字号, 文本)：超宽逐级降字号；最小字号仍放不下则在词边界截断加省略号"""
    text = str(text or "")
    size = fit_size(text, width_cm, base)
    capacity = width_cm * PT_PER_CM / max(1, size)
    if text_em(text) <= capacity:
        return size, text
    keep = max(1.0, capacity - 1.0)          # 留一个省略号的位置
    out, used = "", 0.0
    for ch in text:
        w = ASCII_EM if ord(ch) < 0x2E80 else CJK_EM
        if used + w > keep:
            break
        out += ch
        used += w
    return size, out.rstrip() + "…"


def row_height_cm(size_pt, spacing=1.35, gap_pt=10):
    """一行内容占的高度（cm）：行高 + 段间距"""
    return size_pt * spacing / PT_PER_CM + gap_pt / PT_PER_CM


# ==================== 图片加工（圆角 + 描边 + 投影） ====================

def prepare_image(path, out_dir, theme, border=True, shadow=True, max_side=1600):
    """生成"带圆角/描边/浅投影"的图片副本（带缓存），返回新路径；失败返回原路径"""
    import hashlib
    import os

    from PIL import Image, ImageDraw, ImageFilter

    if not path or not os.path.isfile(path):
        return ""
    cache_dir = os.path.join(out_dir, FRAME_CACHE)
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        return path
    key = hashlib.md5(
        f"{os.path.abspath(path)}|{theme.get('primary')}|{theme.get('line_soft')}|"
        f"{border}|{shadow}".encode("utf-8")).hexdigest()[:12]
    out = os.path.join(cache_dir, f"{key}.png")
    if os.path.isfile(out):
        return out
    try:
        im = Image.open(path).convert("RGBA")
        if max(im.size) > max_side:
            ratio = max_side / float(max(im.size))
            im = im.resize((max(1, int(im.width * ratio)), max(1, int(im.height * ratio))),
                           Image.LANCZOS)
        radius = max(2, int(min(im.size) * FRAME_RADIUS))
        pad = 7 if shadow else FRAME_BORDER
        canvas = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
        if shadow:
            sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).rounded_rectangle(
                [pad, pad + 3, canvas.width - pad, canvas.height - pad + 3],
                radius=radius, fill=(0, 0, 0, 60))
            canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)))
        mask = Image.new("L", im.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1],
                                               radius=radius, fill=255)
        canvas.paste(im, (pad, pad), mask)
        if border:
            ImageDraw.Draw(canvas).rounded_rectangle(
                [pad, pad, canvas.width - pad - 1, canvas.height - pad - 1], radius=radius,
                outline=hex_rgb(theme.get("line_soft", "#DDDDDD")) + (255,), width=FRAME_BORDER)
        canvas.convert("RGB").save(out, "PNG")
        return out
    except Exception:
        return path
