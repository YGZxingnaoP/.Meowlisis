# -*- coding: utf-8 -*-
"""docwriter PPT 版式函数库（v2：约束生成 + 确定性排版，一次成型）。

一步做对的三条规矩
------------------
1. **字号锁定**：正文基准 17pt，只在"这条放不下"时按 17→15→13→11 降级（design.fit_text），
   绝不因为条目多少而整体缩放字号（那会让翻页时字在跳）。
2. **一条一个文本框**：每条独立定位，位置由"行高 × 条数 + 均分间距"算出，
   永不重叠、永不溢出——不需要事后检测与重排。
3. **垂直居中 + 均分**：内容块在内容区居中，间距 = clamp((可用高-内容高)/(n+1), 0.35, 1.1)cm。

统一栅格（16:9，单位 cm）
    W=33.867 H=19.05  边距 2.0  标题基线上方 1.45  内容区 3.2~17.5  页脚线 17.9
"""

from . import design as D

MARGIN = 2.0
CONTENT_TOP = 3.2
CONTENT_BOTTOM = 17.5
TITLE_Y = 1.45
TITLE_H = 1.35
FOOTER_LINE = 17.9


def _content_w():
    return D.PAGE["ppt_w"] - MARGIN * 2


def _rgb(v):
    from pptx.dml.color import RGBColor

    return RGBColor(*D.hex_rgb(v))


def _set_font(run, name):
    """同时设置 latin 与 eastAsia 字体，避免中文回退成方框"""
    from pptx.oxml.ns import qn

    run.font.name = name
    rpr = run.font._rPr
    for tag in ("a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = rpr.makeelement(qn(tag), {})
            rpr.append(el)
        el.set("typeface", name)


def blank(prs):
    """空白版式（所有版式都自绘，不依赖内置母版）"""
    return prs.slides.add_slide(prs.slide_layouts[6])


def rect(slide, x, y, w, h, fill=None, line=None, radius=None):
    """色块 / 细线 / 圆角卡片"""
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Cm

    shape = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    sp = slide.shapes.add_shape(shape, Cm(x), Cm(y), Cm(w), Cm(h))
    sp.shadow.inherit = False
    if radius:
        try:
            sp.adjustments[0] = min(0.5, float(radius) / max(0.1, min(w, h)))
        except Exception:
            pass
    if fill:
        sp.fill.solid()
        sp.fill.fore_color.rgb = _rgb(fill)
    else:
        sp.fill.background()
    if line:
        sp.line.color.rgb = _rgb(line)
    else:
        sp.line.fill.background()
    sp.text_frame.text = ""
    return sp


def text(slide, x, y, w, h, blocks, anchor="t", align="l"):
    """多段文本块。

    blocks: [{"t": 文本, "s": 字号, "b": 粗体, "c": 颜色, "sp": 行距, "sb": 段前,
              "al": 对齐, "dot": 项目符号, "dc": 符号色, "f": 字体, "i": 斜体,
              "runs": [(文本, {覆盖}), ...]}]
    """
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Cm, Pt

    tb = slide.shapes.add_textbox(Cm(x), Cm(y), Cm(w), Cm(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE,
                          "b": MSO_ANCHOR.BOTTOM}[anchor]
    amap = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT,
            "j": PP_ALIGN.JUSTIFY}
    for idx, blk in enumerate(blocks):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.alignment = amap.get(blk.get("al") or align, PP_ALIGN.LEFT)
        p.line_spacing = float(blk.get("sp", 1.3))
        if blk.get("sb"):
            p.space_before = Pt(blk["sb"])
        if blk.get("sa") is not None:
            p.space_after = Pt(blk["sa"])
        fname = blk.get("f") or D.FONT_CN
        size = blk.get("s", D.SIZE["ppt_body"])
        color = blk.get("c") or "#333333"
        if blk.get("dot"):
            r = p.add_run()
            r.text = "▪ "
            r.font.size = Pt(max(10, size - 2))
            r.font.bold = True
            r.font.color.rgb = _rgb(blk.get("dc") or D.THEMES["tech"]["secondary"])
            _set_font(r, fname)
        for piece in (blk.get("runs") or [(blk.get("t") or "", {})]):
            r = p.add_run()
            r.text = str(piece[0])
            ov = piece[1] if len(piece) > 1 else {}
            r.font.size = Pt(ov.get("s", size))
            r.font.bold = bool(ov.get("b", blk.get("b")))
            r.font.italic = bool(ov.get("i", blk.get("i")))
            r.font.color.rgb = _rgb(ov.get("c") or color)
            _set_font(r, ov.get("f") or fname)
    return tb


def image(slide, path, x, y, w, h, theme=None, framed=True):
    """按框等比缩放居中放图（自动加圆角/描边/浅投影），返回形状或 None"""
    from pptx.util import Cm

    if not path:
        return None
    src = path
    if framed and theme is not None:
        import os

        src = D.prepare_image(path, os.path.dirname(os.path.abspath(path)), theme)
    try:
        from PIL import Image

        iw, ih = Image.open(src).size
    except Exception:
        return None
    if not iw or not ih:
        return None
    scale = min(w / iw, h / ih)
    dw, dh = iw * scale, ih * scale
    try:
        return slide.shapes.add_picture(src, Cm(x + (w - dw) / 2), Cm(y + (h - dh) / 2),
                                       Cm(dw), Cm(dh))
    except Exception:
        return None


def _placeholder(slide, theme, x, y, w, h, note="（配图缺失）"):
    """图片缺失时的占位块，保证版面不塌"""
    rect(slide, x, y, w, h, fill=theme["tint8"], line=theme["line_soft"])
    text(slide, x, y + h / 2 - 0.6, w, 1.2,
         [{"t": note, "s": D.SIZE["ppt_small"], "c": theme["muted"], "sp": 1.0, "al": "c"}],
         anchor="m", align="c")


def _title(slide, theme, title, kicker=None):
    """标题区三件套：小标签 + 标题（超长自动降字号）+ 主色短线"""
    if kicker:
        text(slide, MARGIN, TITLE_Y - 0.42, _content_w(), 0.8,
             [{"t": str(kicker), "s": D.SIZE["ppt_caption"], "b": True,
               "c": theme["secondary"], "sp": 1.0}])
        ty = TITLE_Y + 0.28
    else:
        ty = TITLE_Y
    size, shown = D.fit_text(title, _content_w() - 1.5, D.SIZE["ppt_title"])
    text(slide, MARGIN, ty, _content_w() - 1.0, TITLE_H,
         [{"t": shown, "s": size, "b": True, "c": theme["ink"], "sp": 1.05}])
    rect(slide, MARGIN, ty + 1.28, 2.4, 0.1, fill=theme["primary"])


def _footer(slide, theme, page_no=None, note=""):
    """页脚：细分隔线 + 文档名 + 页码"""
    w = D.PAGE["ppt_w"]
    rect(slide, MARGIN, FOOTER_LINE, w - MARGIN * 2, 0.02, fill=theme["line_soft"])
    if note:
        text(slide, MARGIN, FOOTER_LINE + 0.15, w / 2, 0.7,
             [{"t": str(note)[:40], "s": D.SIZE["ppt_caption"], "c": theme["muted"], "sp": 1.0}])
    if page_no:
        text(slide, w - MARGIN - 3, FOOTER_LINE + 0.15, 3, 0.7,
             [{"t": "%02d" % int(page_no), "s": D.SIZE["ppt_caption"], "b": True,
               "c": theme["primary"], "sp": 1.0, "al": "r"}], align="r")


def _place_list(slide, theme, items, x, top, w, bottom, base=None, dot=True, dot_color=None,
                align="l"):
    """核心排版器：每条一个文本框，垂直居中 + 均分间距，永不重叠/溢出。

    返回实际占用的总高（cm）。
    """
    clean = [str(i).strip() for i in (items or []) if str(i).strip()]
    if not clean:
        return 0.0
    base = base or D.SIZE["ppt_body"]
    rows = []
    for it in clean:
        size, shown = D.fit_text(it, w - 0.55, base)
        rows.append((size, shown, D.row_height_cm(size, 1.35, 9)))
    total = sum(r[2] for r in rows)
    avail = max(0.6, bottom - top)
    gap = max(0.28, min(1.05, (avail - total) / (len(rows) + 1)))
    block = total + gap * (len(rows) - 1)
    y = top + max(0.0, (avail - block) / 2.0)
    for size, shown, h in rows:
        text(slide, x, y, w, h,
             [{"t": shown, "s": size, "c": theme["ink"], "sp": 1.35, "dot": dot,
               "dc": dot_color or theme["secondary"], "al": align}], align=align)
        y += h + gap
    return block


# ==================== 基础版式 ====================

def cover(prs, theme, title, subtitle="", meta=""):
    """封面：左主色带 + 强调短线 + 大标题"""
    s = blank(prs)
    w, h = D.PAGE["ppt_w"], D.PAGE["ppt_h"]
    rect(s, 0, 0, w, h, fill=theme["bg"])
    rect(s, 0, 0, 0.6, h, fill=theme["primary"])
    rect(s, MARGIN + 0.4, 6.2, 3.2, 0.16, fill=theme["accent"])
    size, shown = D.fit_text(title, w - MARGIN * 2 - 2.5, D.SIZE["ppt_big"])
    text(s, MARGIN + 0.4, 7.0, w - MARGIN * 2 - 2.5, 4.4,
         [{"t": shown, "s": size, "b": True, "c": theme["ink"], "sp": 1.15}])
    if subtitle:
        ssize, sshown = D.fit_text(subtitle, w - MARGIN * 2 - 3.0, D.SIZE["cover_sub"])
        text(s, MARGIN + 0.4, 11.6, w - MARGIN * 2 - 3.0, 1.6,
             [{"t": sshown, "s": ssize, "c": theme["muted"], "sp": 1.2}])
    if meta:
        text(s, MARGIN + 0.4, 16.3, w - MARGIN * 2, 1.2,
             [{"t": str(meta), "s": D.SIZE["ppt_caption"], "c": theme["muted"], "sp": 1.0}])
    rect(s, w - 8.6, 3.4, 5.2, 5.2, fill=theme["tint8"], radius=0.25)
    rect(s, w - 7.9, 4.1, 3.8, 3.8, fill=theme["tint14"], radius=0.2)
    return s


def toc(prs, theme, items, page_no=None, doc_title=""):
    """目录：编号 + 均分两列"""
    s = blank(prs)
    w = D.PAGE["ppt_w"]
    _title(s, theme, "目录", kicker="CONTENTS")
    items = [str(i) for i in (items or [])]
    half = (len(items) + 1) // 2
    colw = (_content_w() - 1.4) / 2
    for col, chunk in enumerate((items[:half], items[half:])):
        blocks = []
        for i, it in enumerate(chunk):
            no = col * half + i + 1
            size, shown = D.fit_text(it, colw - 1.6, D.SIZE["ppt_body"])
            blocks.append({"runs": [("%02d   " % no, {"c": theme["accent"], "b": True}),
                                    (shown, {})],
                           "s": size, "c": theme["ink"], "sp": 1.2, "sb": 12 if i else 0})
        text(s, MARGIN + col * (colw + 1.4), CONTENT_TOP + 1.0, colw,
             CONTENT_BOTTOM - CONTENT_TOP - 1.2, blocks)
    _footer(s, theme, page_no, doc_title)
    return s


def section(prs, theme, title, no="", desc="", page_no=None, doc_title=""):
    """过渡页：大编号 + 章节名"""
    s = blank(prs)
    w, h = D.PAGE["ppt_w"], D.PAGE["ppt_h"]
    rect(s, 0, 0, w, h, fill=theme["tint8"])
    rect(s, 0, 0, 0.5, h, fill=theme["primary"])
    rect(s, MARGIN, 5.3, 7.6, 4.6, fill=theme["tint14"], radius=0.3)
    if no:
        text(s, MARGIN, 5.5, 7.6, 4.2,
             [{"t": str(no), "s": D.SIZE["ppt_no"], "b": True, "c": theme["primary"], "sp": 0.95,
               "al": "c"}], anchor="m", align="c")
    size, shown = D.fit_text(title, w - MARGIN * 2 - 1, D.SIZE["ppt_title"])
    text(s, MARGIN, 10.9, w - MARGIN * 2 - 1, 2.6,
         [{"t": shown, "s": size, "b": True, "c": theme["ink"], "sp": 1.1}])
    rect(s, MARGIN, 13.5, 2.4, 0.12, fill=theme["accent"])
    if desc:
        dsize, dshown = D.fit_text(desc, w - MARGIN * 2 - 7, D.SIZE["ppt_body"])
        text(s, MARGIN, 13.9, w - MARGIN * 2 - 7, 2.2,
             [{"t": dshown, "s": dsize, "c": theme["muted"], "sp": 1.3}])
    return s


def bullets(prs, theme, title, items, kicker=None, page_no=None, doc_title=""):
    """要点页：字号锁定 + 垂直均分（不再随条数改字号）"""
    s = blank(prs)
    _title(s, theme, title, kicker=kicker)
    _place_list(s, theme, items, MARGIN + 0.3, CONTENT_TOP + 0.2, _content_w() - 0.8,
                CONTENT_BOTTOM - 0.3, base=D.SIZE["ppt_body"], dot=True,
                dot_color=theme["secondary"])
    _footer(s, theme, page_no, doc_title)
    return s


def two_col(prs, theme, title, left_title, left_items, right_title, right_items,
            page_no=None, doc_title=""):
    """两栏对比：每栏一张浅色卡片"""
    s = blank(prs)
    _title(s, theme, title)
    colw = (_content_w() - 1.2) / 2
    top = CONTENT_TOP + 0.5
    bottom = CONTENT_BOTTOM - 0.2
    for i, (ct, ci) in enumerate(((left_title, left_items), (right_title, right_items))):
        x = MARGIN + i * (colw + 1.2)
        accent = theme["primary"] if i == 0 else theme["secondary"]
        rect(s, x, top, colw, bottom - top, fill=theme["tint8"] if i == 0 else theme["card"],
             radius=0.18)
        rect(s, x, top, colw, 0.12, fill=accent)
        if ct:
            text(s, x + 0.45, top + 0.35, colw - 0.9, 1.0,
                 [{"t": str(ct), "s": D.SIZE["ppt_h2"], "b": True, "c": theme["ink"],
                   "sp": 1.1}])
        _place_list(s, theme, ci, x + 0.45, top + 1.7, colw - 0.9, bottom - 0.35,
                    base=D.SIZE["ppt_body2"], dot=True, dot_color=accent)
    _footer(s, theme, page_no, doc_title)
    return s


def image_right(prs, theme, title, items, image_path, caption="", page_no=None, doc_title=""):
    """左文右图：文字左栏 + 图片固定框（圆角描边）"""
    s = blank(prs)
    w = D.PAGE["ppt_w"]
    _title(s, theme, title)
    textw = (_content_w() - 1.2) * 0.46
    imgx = MARGIN + textw + 1.2
    imgw = w - MARGIN - imgx
    cap_h = 0.9 if caption else 0.0
    _place_list(s, theme, items, MARGIN + 0.2, CONTENT_TOP + 0.35, textw - 0.4,
                CONTENT_BOTTOM - 0.3, base=D.SIZE["ppt_body2"], dot=True)
    box_h = CONTENT_BOTTOM - CONTENT_TOP - cap_h - 0.2
    if not image(s, image_path, imgx, CONTENT_TOP + 0.2, imgw, box_h, theme):
        _placeholder(s, theme, imgx, CONTENT_TOP + 0.2, imgw, box_h)
    if caption:
        text(s, imgx, CONTENT_BOTTOM - 0.62, imgw, 0.7,
             [{"t": str(caption), "s": D.SIZE["ppt_caption"], "c": theme["muted"], "sp": 1.0,
               "al": "c"}], align="c")
    _footer(s, theme, page_no, doc_title)
    return s


def full_image(prs, theme, title, image_path, caption="", points=None, page_no=None,
               doc_title=""):
    """大图页"""
    s = blank(prs)
    w = D.PAGE["ppt_w"]
    _title(s, theme, title)
    pts = [str(p) for p in (points or []) if str(p).strip()]
    pt_h = 1.3 if pts else 0.0
    cap_h = 0.85 if caption else 0.0
    box_h = CONTENT_BOTTOM - CONTENT_TOP - pt_h - cap_h - 0.25
    if not image(s, image_path, MARGIN, CONTENT_TOP + 0.15, _content_w(), box_h, theme):
        _placeholder(s, theme, MARGIN, CONTENT_TOP + 0.15, _content_w(), box_h)
    y = CONTENT_TOP + 0.15 + box_h
    if caption:
        text(s, MARGIN, y + 0.08, _content_w(), 0.7,
             [{"t": str(caption), "s": D.SIZE["ppt_caption"], "c": theme["muted"], "sp": 1.0,
               "al": "c"}], align="c")
        y += 0.8
    if pts:
        _place_list(s, theme, pts, MARGIN + 0.3, y + 0.05, _content_w() - 0.6,
                    CONTENT_BOTTOM - 0.1, base=D.SIZE["ppt_small"], dot=True)
    _footer(s, theme, page_no, doc_title)
    return s


def chart(prs, theme, title, image_path, points=None, caption="", page_no=None, doc_title=""):
    """图表页：左图表 + 右结论"""
    s = blank(prs)
    w = D.PAGE["ppt_w"]
    _title(s, theme, title)
    pts = [str(p) for p in (points or []) if str(p).strip()]
    chartw = (_content_w() - 1.4) * (0.62 if pts else 1.0)
    cap_h = 0.8 if caption else 0.0
    box_h = CONTENT_BOTTOM - CONTENT_TOP - cap_h - 0.2
    if not image(s, image_path, MARGIN, CONTENT_TOP + 0.15, chartw, box_h, theme):
        _placeholder(s, theme, MARGIN, CONTENT_TOP + 0.15, chartw, box_h, "（图表缺失）")
    if caption:
        text(s, MARGIN, CONTENT_TOP + 0.15 + box_h + 0.05, chartw, 0.7,
             [{"t": str(caption), "s": D.SIZE["ppt_caption"], "c": theme["muted"], "sp": 1.0,
               "al": "c"}], align="c")
    if pts:
        x = MARGIN + chartw + 1.4
        colw = w - MARGIN - x
        rect(s, x - 0.35, CONTENT_TOP + 0.35, colw + 0.35, CONTENT_BOTTOM - CONTENT_TOP - 0.7,
             fill=theme["card"], radius=0.18)
        text(s, x, CONTENT_TOP + 0.6, colw, 1.0,
             [{"t": "关键结论", "s": D.SIZE["ppt_h2"], "b": True, "c": theme["primary"],
               "sp": 1.1}])
        _place_list(s, theme, pts, x, CONTENT_TOP + 1.9, colw - 0.4,
                    CONTENT_BOTTOM - 0.6, base=D.SIZE["ppt_body2"], dot=True,
                    dot_color=theme["accent"])
    _footer(s, theme, page_no, doc_title)
    return s


def table(prs, theme, title, header, rows, page_no=None, doc_title=""):
    """表格页：主题色表头 + 浅色斑马纹 + 字号自适应"""
    from pptx.util import Cm, Pt

    s = blank(prs)
    _title(s, theme, title)
    header = [str(h) for h in (header or [])]
    rows = [[str(c) for c in r] for r in (rows or [])]
    cols = max([len(header)] + [len(r) for r in rows] or [1]) or 1
    header = header + [""] * (cols - len(header))
    rows = [r + [""] * (cols - len(r)) for r in rows]
    header = header[:4] or [""]
    cols = len(header)
    rows = [r[:cols] for r in rows][:8]
    total = len(rows) + 1
    avail_h = CONTENT_BOTTOM - CONTENT_TOP - 0.6
    th = min(1.15, avail_h / max(total, 1))
    shape = s.shapes.add_table(total, cols, Cm(MARGIN), Cm(CONTENT_TOP + 0.45),
                               Cm(_content_w()), Cm(th * total))
    tbl = shape.table
    tbl.first_row = True
    for ri, row in enumerate([header] + rows):
        for ci, val in enumerate(row):
            cell = tbl.cell(ri, ci)
            base = D.SIZE["ppt_small"] if not ri else D.SIZE["ppt_caption"]
            size = D.fit_size(val, _content_w() / cols - 0.35, base)
            cell.text = str(val)
            cell.margin_top = cell.margin_bottom = Pt(2)
            cell.margin_left = cell.margin_right = Pt(7)
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(theme["primary"] if ri == 0 else
                                            (theme["tint8"] if ri % 2 else theme["bg"]))
            para = cell.text_frame.paragraphs[0]
            para.line_spacing = 1.05
            for run in para.runs:
                run.font.size = Pt(size)
                run.font.bold = (ri == 0)
                run.font.color.rgb = _rgb("#FFFFFF" if ri == 0 else theme["ink"])
                _set_font(run, D.FONT_CN)
    _footer(s, theme, page_no, doc_title)
    return s


def quote(prs, theme, text_str, author="", page_no=None, doc_title=""):
    """金句页"""
    s = blank(prs)
    w = D.PAGE["ppt_w"]
    rect(s, 0, 0, w, D.PAGE["ppt_h"], fill=theme["tint8"])
    rect(s, MARGIN + 1.2, 6.0, 3.0, 0.14, fill=theme["primary"])
    size, shown = D.fit_text(text_str, w - (MARGIN + 1.5) * 2, D.SIZE["ppt_quote"])
    text(s, MARGIN + 1.5, 6.6, w - (MARGIN + 1.5) * 2, 6.0,
         [{"t": shown, "s": size, "b": True, "c": theme["ink"], "sp": 1.35}])
    if author:
        text(s, MARGIN + 1.5, 14.2, w - (MARGIN + 1.5) * 2, 1.2,
             [{"t": "—— " + str(author), "s": D.SIZE["ppt_small"], "c": theme["muted"],
               "sp": 1.1, "al": "r"}], align="r")
    _footer(s, theme, page_no, doc_title)
    return s


def end(prs, theme, text_str="谢谢观看", sub=""):
    """结尾页"""
    s = blank(prs)
    w, h = D.PAGE["ppt_w"], D.PAGE["ppt_h"]
    rect(s, 0, 0, w, h, fill=theme["bg"])
    rect(s, w / 2 - 2.2, 8.1, 4.4, 0.14, fill=theme["primary"])
    text(s, 0, 8.7, w, 2.6,
         [{"t": str(text_str or "谢谢观看"), "s": D.SIZE["ppt_big"], "b": True, "c": theme["ink"],
           "sp": 1.1, "al": "c"}], align="c")
    if sub:
        text(s, 0, 11.7, w, 1.4,
             [{"t": str(sub), "s": D.SIZE["ppt_h2"], "c": theme["muted"], "sp": 1.2,
               "al": "c"}], align="c")
    return s


# ==================== 高观感版式（v2 新增） ====================

def kpi(prs, theme, title, cards, kicker=None, page_no=None, doc_title=""):
    """数据大卡页：3 个数字卡（cards=[{"value","label","note"}]）"""
    s = blank(prs)
    _title(s, theme, title, kicker=kicker)
    cards = [c if isinstance(c, dict) else {"value": str(c)} for c in (cards or [])][:3]
    if not cards:
        cards = [{"value": "—", "label": "暂无数据"}]
    gap = 1.0
    n = len(cards)
    cw = (_content_w() - gap * (n - 1)) / n
    top, bottom = CONTENT_TOP + 1.6, CONTENT_BOTTOM - 1.0
    accents = (theme["primary"], theme["secondary"], theme["accent"])
    for i, c in enumerate(cards):
        x = MARGIN + i * (cw + gap)
        rect(s, x, top, cw, bottom - top, fill=theme["tint8"], radius=0.22)
        rect(s, x, top, cw, 0.14, fill=accents[i % 3])
        val = str(c.get("value") or c.get("num") or "—")
        vsize, vshown = D.fit_text(val, cw - 1.2, D.SIZE["ppt_display"])
        text(s, x + 0.6, top + 0.9, cw - 1.2, 2.4,
             [{"t": vshown, "s": vsize, "b": True, "c": accents[i % 3], "sp": 1.0}])
        lab = str(c.get("label") or "")
        if lab:
            lsize, lshown = D.fit_text(lab, cw - 1.2, D.SIZE["ppt_body2"])
            text(s, x + 0.6, top + 3.5, cw - 1.2, 1.0,
                 [{"t": lshown, "s": lsize, "b": True, "c": theme["ink"], "sp": 1.1}])
        note = str(c.get("note") or "")
        if note:
            nsize, nshown = D.fit_text(note, cw - 1.2, D.SIZE["ppt_caption"])
            text(s, x + 0.6, top + 4.5, cw - 1.2, 2.0,
                 [{"t": nshown, "s": nsize, "c": theme["muted"], "sp": 1.25}])
    _footer(s, theme, page_no, doc_title)
    return s


def timeline(prs, theme, title, nodes, page_no=None, doc_title=""):
    """时间线页：横轴 + 节点 + 上下交错说明（nodes=[{"label","title","desc"}]）"""
    s = blank(prs)
    _title(s, theme, title)
    nodes = [n if isinstance(n, dict) else {"title": str(n)} for n in (nodes or [])][:5]
    if not nodes:
        nodes = [{"title": "暂无"}]
    n = len(nodes)
    ax_y = (CONTENT_TOP + CONTENT_BOTTOM) / 2 - 0.2
    left, right = MARGIN + 1.0, D.PAGE["ppt_w"] - MARGIN - 1.0
    rect(s, left, ax_y, right - left, 0.08, fill=theme["line_soft"])
    step = (right - left) / max(1, n)
    for i, nd in enumerate(nodes):
        cx = left + step * (i + 0.5)
        rect(s, cx - 0.22, ax_y - 0.19, 0.44, 0.44, fill=theme["primary"], radius=0.22)
        up = (i % 2 == 0)
        bw = step - 0.6
        bx = cx - bw / 2
        if up:
            by = ax_y - 4.6
        else:
            by = ax_y + 0.9
        rect(s, bx, by, bw, 3.6, fill=theme["card"], radius=0.16)
        lab = str(nd.get("label") or "")
        if lab:
            text(s, bx + 0.35, by + 0.28, bw - 0.7, 0.8,
                 [{"t": lab, "s": D.SIZE["ppt_caption"], "b": True,
                   "c": theme["secondary"], "sp": 1.0}])
        t = str(nd.get("title") or "")
        tsize, tshown = D.fit_text(t, bw - 0.7, D.SIZE["ppt_body2"])
        text(s, bx + 0.35, by + (1.0 if lab else 0.4), bw - 0.7, 1.2,
             [{"t": tshown, "s": tsize, "b": True, "c": theme["ink"], "sp": 1.15}])
        d = str(nd.get("desc") or "")
        if d:
            dsize, dshown = D.fit_text(d, bw - 0.7, D.SIZE["ppt_caption"])
            text(s, bx + 0.35, by + (2.1 if lab else 1.5), bw - 0.7, 1.4,
                 [{"t": dshown, "s": dsize, "c": theme["muted"], "sp": 1.2}])
    _footer(s, theme, page_no, doc_title)
    return s


def matrix(prs, theme, title, cells, page_no=None, doc_title=""):
    """对比矩阵：2×2 卡片（cells=[{"title","items"}]）"""
    s = blank(prs)
    _title(s, theme, title)
    cells = [c if isinstance(c, dict) else {"title": str(c)} for c in (cells or [])][:4]
    while len(cells) < 4:
        cells.append({"title": "", "items": []})
    top, bottom = CONTENT_TOP + 0.35, CONTENT_BOTTOM - 0.3
    gap = 1.0
    cw = (_content_w() - gap) / 2
    ch = (bottom - top - gap) / 2
    accents = (theme["primary"], theme["secondary"], theme["accent"], theme["muted"])
    for i, c in enumerate(cells):
        x = MARGIN + (i % 2) * (cw + gap)
        y = top + (i // 2) * (ch + gap)
        rect(s, x, y, cw, ch, fill=theme["card"], radius=0.18)
        rect(s, x, y, cw, 0.12, fill=accents[i % 4])
        t = str(c.get("title") or "")
        if t:
            tsize, tshown = D.fit_text(t, cw - 1.0, D.SIZE["ppt_h2"])
            text(s, x + 0.5, y + 0.3, cw - 1.0, 1.0,
                 [{"t": tshown, "s": tsize, "b": True, "c": theme["ink"], "sp": 1.1}])
        items = c.get("items") or c.get("bullets") or c.get("text") or []
        if isinstance(items, str):
            items = [items]
        _place_list(s, theme, items, x + 0.5, y + 1.3, cw - 1.0, y + ch - 0.35,
                    base=D.SIZE["ppt_small"], dot=True, dot_color=accents[i % 4])
    _footer(s, theme, page_no, doc_title)
    return s


def grid(prs, theme, title, images, page_no=None, doc_title=""):
    """图片墙：≤4 张等分 + 统一图注（images=[{"path","caption"}]）"""
    s = blank(prs)
    _title(s, theme, title)
    items = [i if isinstance(i, dict) else {"path": str(i)} for i in (images or [])][:4]
    if not items:
        items = [{}]
    n = len(items)
    cols = 2 if n > 1 else 1
    rows = 2 if n > 2 else 1
    gap = 0.9
    top, bottom = CONTENT_TOP + 0.3, CONTENT_BOTTOM - 0.2
    cw = (_content_w() - gap * (cols - 1)) / cols
    ch = (bottom - top - gap * (rows - 1)) / rows
    for i, it in enumerate(items):
        x = MARGIN + (i % cols) * (cw + gap)
        y = top + (i // cols) * (ch + gap)
        cap = str(it.get("caption") or "")
        box_h = ch - (0.85 if cap else 0.0)
        if not image(s, it.get("path"), x, y, cw, box_h, theme):
            _placeholder(s, theme, x, y, cw, box_h)
        if cap:
            size, shown = D.fit_text(cap, cw - 0.4, D.SIZE["ppt_caption"])
            text(s, x, y + box_h + 0.05, cw, 0.7,
                 [{"t": shown, "s": size, "c": theme["muted"], "sp": 1.0, "al": "c"}], align="c")
    _footer(s, theme, page_no, doc_title)
    return s


LAYOUTS = {
    "cover": cover, "toc": toc, "section": section, "bullets": bullets, "two_col": two_col,
    "image_right": image_right, "full_image": full_image, "chart": chart, "table": table,
    "quote": quote, "end": end, "kpi": kpi, "timeline": timeline, "matrix": matrix,
    "grid": grid,
}

LAYOUT_HINT = (
    "可用版式(layout)：cover 封面 / toc 目录 / section 章节页 / bullets 要点页 / "
    "kpi 数据大卡页(3 个数字) / timeline 时间线(3~5 节点) / matrix 对比矩阵(4 格) / "
    "table 表格页 / chart 图表页 / image_right 左文右图 / full_image 整页大图 / "
    "grid 图片墙(2~4 图) / two_col 两栏对比 / quote 金句页 / end 结尾页"
)
