# -*- coding: utf-8 -*-
"""数据与图表：结构化校验 / 聚合 / 表格 / matplotlib 图表。

数据来源是「联网检索后由模型抽取的结构化 JSON」，所以这里要顶住脏数据：
    * 数字带单位（1.2亿 / 3.5万 / 12% / 1,234 / ≈5.6）
    * 键名不统一（name/title/项目/名称）
    * 缺失值、重复行、单位混用

对外
----
    normalize(rows)                     → [{"name","value","unit","year","source"}]
    aggregate(rows, op, ...)            → 聚合结果（top/sum/avg/ratio/yoy）
    make_table(rows, ...)               → (header, rows) 供 docx/ppt 表格
    make_chart(rows, kind, ...)         → 图表 PNG 路径
"""

import os
import re

# 数值单位换算
_SCALE = {"万": 1e4, "亿": 1e8, "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6,
          "千": 1e3, "百万": 1e6, "十亿": 1e9}

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)*")

_KEY_ALIAS = {
    "name": ("name", "title", "label", "item", "key", "项目", "名称", "指标", "国家", "地区", "公司", "类别"),
    "value": ("value", "val", "amount", "num", "count", "number", "数值", "值", "数量", "金额", "份额", "占比"),
    "unit": ("unit", "单位",),
    "year": ("year", "date", "time", "年份", "时间", "日期", "期间"),
    "source": ("source", "url", "ref", "link", "来源", "链接", "出处"),
}


# ==================== 清洗 ====================

def parse_number(text):
    """把「1.2亿 / 3,456 / 12% / ≈5.6万」解析成 float；失败返回 None"""
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text or "").strip()
    if not s:
        return None
    s = s.replace("，", ",").replace(" ", "")
    m = _NUM_RE.search(s)
    if not m:
        return None
    raw = m.group(0).replace(",", "")
    # 处理 "1.234,56" 这类欧洲格式
    if raw.count(",") and raw.count("."):
        raw = raw.replace(",", "")
    try:
        val = float(raw)
    except Exception:
        return None
    tail = s[m.end():m.end() + 3]
    for unit, factor in _SCALE.items():
        if tail.startswith(unit):
            val *= factor
            break
    if s.rstrip().endswith("%"):
        val = val  # 百分数保持原值，单位记为 %
    return val


def _pick(row, field):
    """按别名取字段"""
    for key in _KEY_ALIAS.get(field, (field,)):
        if key in row and str(row[key]).strip() not in ("", "None", "null", "-"):
            return row[key]
        for rk in row:
            if str(rk).strip().lower() == str(key).lower():
                if str(row[rk]).strip() not in ("", "None", "null", "-"):
                    return row[rk]
    return ""


def normalize(rows):
    """统一结构 + 数值化 + 去重 + 去空"""
    out, seen = [], set()
    for row in (rows or []):
        if isinstance(row, (list, tuple)):
            row = {"name": row[0] if len(row) > 0 else "",
                   "value": row[1] if len(row) > 1 else "",
                   "unit": row[2] if len(row) > 2 else ""}
        if not isinstance(row, dict):
            continue
        name = str(_pick(row, "name")).strip()
        raw_val = _pick(row, "value")
        num = parse_number(raw_val)
        if not name and num is None:
            continue
        unit = str(_pick(row, "unit")).strip()
        if not unit:
            txt = str(raw_val)
            unit = "%" if txt.strip().endswith("%") else ""
        item = {"name": name or str(raw_val), "value": num,
                "unit": unit, "year": str(_pick(row, "year")).strip(),
                "source": str(_pick(row, "source")).strip()}
        key = (item["name"], item["value"], item["year"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def numeric_rows(rows):
    """只保留有数值的行"""
    return [r for r in normalize(rows) if r.get("value") is not None]


# ==================== 聚合 ====================

OPS = ("top_n", "sum", "avg", "max", "min", "count", "ratio", "yoy")


def aggregate(rows, op="top_n", top=10, group=None):
    """聚合计算。

    op: top_n 排名 / sum 合计 / avg 均值 / max / min / count 计数
        ratio 占比（带 %）/ yoy 同比（需 year 字段，返回 [本期, 上期, 变化%]）
    group: 指定分组字段名（默认按 name 分组）
    """
    data = numeric_rows(rows)
    if not data:
        return []
    key = group or "name"
    buckets = {}
    for r in data:
        k = str(r.get(key) or r.get("name") or "未命名")
        buckets.setdefault(k, []).append(r["value"])
    grouped = [{"name": k, "value": v[0], "unit": ""} for k, v in buckets.items()]

    if op in ("sum", "avg", "max", "min", "count"):
        vals = [r["value"] for r in grouped]
        if op == "sum":
            return [{"name": "合计", "value": round(sum(vals), 4), "unit": ""}]
        if op == "avg":
            return [{"name": "平均", "value": round(sum(vals) / len(vals), 4), "unit": ""}]
        if op == "max":
            return [max(grouped, key=lambda x: x["value"])]
        if op == "min":
            return [min(grouped, key=lambda x: x["value"])]
        return [{"name": "条目数", "value": len(vals), "unit": "条"}]

    if op == "ratio":
        total = sum(abs(r["value"]) for r in grouped) or 1
        res = [{"name": r["name"], "value": round(r["value"] / total * 100, 2), "unit": "%"}
               for r in sorted(grouped, key=lambda x: -abs(x["value"]))]
        return res[:max(1, top)]

    if op == "yoy":
        years = sorted({r["year"] for r in data if r.get("year")})
        if len(years) < 2:
            return []
        cur, prev = years[-1], years[-2]
        pick = lambda y: sum(r["value"] for r in data if r["year"] == y)  # noqa: E731
        a, b = pick(cur), pick(prev)
        change = ((a - b) / b * 100) if b else None
        return [{"name": f"{prev}", "value": round(b, 4), "unit": ""},
                {"name": f"{cur}", "value": round(a, 4), "unit": ""},
                {"name": "同比变化", "value": round(change, 2) if change is not None else None,
                 "unit": "%"}]

    return sorted(grouped, key=lambda x: -abs(x["value"]))[:max(1, top)]


def make_table(rows, header=None, max_rows=12, extra_cols=None):
    """转成 (header, rows) 供文档/PPT 表格"""
    data = normalize(rows)
    if not data:
        return [], []
    header = header or ["名称", "数值", "单位"]
    body = []
    for r in data[:max_rows]:
        val = r["value"]
        val_txt = "" if val is None else (f"{val:,.2f}".rstrip("0").rstrip(".")
                                          if abs(val) < 1e6 else f"{val:,.0f}")
        body.append([r["name"], val_txt, r["unit"]])
    if extra_cols:
        header = header + list(extra_cols)
    return header, body


# ==================== 图表 ====================

_FONT_READY = None


def use_cjk_font():
    """固定中文字体（否则图表中文变方框）"""
    global _FONT_READY
    if _FONT_READY is not None:
        return _FONT_READY
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager, rcParams

    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
                 "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc"):
        if os.path.isfile(path):
            try:
                font_manager.fontManager.addfont(path)
                name = font_manager.FontProperties(fname=path).get_name()
                rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
                rcParams["axes.unicode_minus"] = False
                _FONT_READY = name
                return name
            except Exception:
                continue
    _FONT_READY = ""
    return ""


CHART_KINDS = ("bar", "barh", "line", "pie", "area", "scatter", "stacked")


def make_chart(rows, out_dir, kind="bar", title="", filename="chart", theme=None,
               top=8, xlabel="", ylabel="", label_values=True):
    """生成图表 PNG，返回路径（失败返回 ""）"""
    data = numeric_rows(rows)
    if not data:
        return ""
    name = use_cjk_font()
    import matplotlib.pyplot as plt

    from .design import get_theme, hex_rgb

    th = get_theme(theme)
    primary = [c / 255 for c in hex_rgb(th["primary"])]
    secondary = [c / 255 for c in hex_rgb(th["secondary"])]
    accent = [c / 255 for c in hex_rgb(th["accent"])]
    ink = [c / 255 for c in hex_rgb(th["ink"])]
    muted = [c / 255 for c in hex_rgb(th["muted"])]

    kinds = {"bar": "bar", "barh": "barh", "line": "line", "area": "area",
             "pie": "pie", "scatter": "scatter", "stacked": "stack"}
    kind = kind if kind in kinds else "bar"

    if kind == "pie":
        data = data[:max(2, top)]
    else:
        data = sorted(data, key=lambda r: -abs(r["value"]))[:max(1, top)]
        data = list(reversed(data)) if kind == "barh" else data

    labels = [str(r["name"])[:12] for r in data]
    values = [r["value"] for r in data]
    unit = next((r["unit"] for r in data if r.get("unit")), "")

    fig, ax = plt.subplots(figsize=(8.4, 4.6), dpi=200)
    fig.patch.set_facecolor("white")
    try:
        if kind == "pie":
            ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=110,
                   colors=[primary, secondary, accent, muted] * 3,
                   textprops={"fontsize": 9, "color": ink}, wedgeprops={"width": 0.42})
            ax.axis("equal")
        elif kind == "line" or kind == "area":
            xs = list(range(len(labels)))
            if kind == "area":
                ax.fill_between(xs, values, color=primary, alpha=0.18)
            ax.plot(xs, values, color=primary, linewidth=2.4, marker="o",
                    markersize=4.5, markerfacecolor="white", markeredgewidth=1.8)
            ax.set_xticks(xs)
            ax.set_xticklabels(labels, fontsize=9, color=ink, rotation=0)
            ax.grid(axis="y", color="#E6E6E6", linewidth=0.8)
            ax.set_axisbelow(True)
            for x, v in zip(xs, values):
                ax.annotate(_fmt(v, unit), (x, v), textcoords="offset points",
                            xytext=(0, 7), ha="center", fontsize=8, color=muted)
        elif kind == "scatter":
            ax.scatter(range(len(labels)), values, s=70, color=primary, alpha=0.85)
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels(labels, fontsize=9, color=ink)
            ax.grid(color="#EFEFEF", linewidth=0.8)
        else:
            colors = [primary if i % 2 == 0 else secondary for i in range(len(labels))]
            if kind == "barh":
                bars = ax.barh(labels, values, color=colors, height=0.62)
                ax.grid(axis="x", color="#EDEDED", linewidth=0.8)
                ax.set_axisbelow(True)
            else:
                bars = ax.bar(labels, values, color=colors, width=0.62)
                ax.grid(axis="y", color="#EDEDED", linewidth=0.8)
                ax.set_axisbelow(True)
            if label_values:
                for b, v in zip(bars, values):
                    if kind == "barh":
                        ax.annotate(_fmt(v, unit), (b.get_width(), b.get_y() + b.get_height() / 2),
                                    textcoords="offset points", xytext=(6, 0),
                                    va="center", fontsize=8.5, color=muted)
                    else:
                        ax.annotate(_fmt(v, unit), (b.get_x() + b.get_width() / 2, b.get_height()),
                                    textcoords="offset points", xytext=(0, 5),
                                    ha="center", fontsize=8.5, color=muted)
            ax.tick_params(axis="x", labelsize=9, colors=ink)
            ax.tick_params(axis="y", labelsize=9, colors=ink)

        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color("#DDDDDD")
        if title:
            ax.set_title(str(title), fontsize=13, color=ink, pad=12, fontweight="bold")
        if xlabel and kind not in ("pie",):
            ax.set_xlabel(str(xlabel), fontsize=9.5, color=muted)
        if ylabel and kind not in ("pie",):
            ax.set_ylabel(str(ylabel), fontsize=9.5, color=muted)
        fig.tight_layout()
        os.makedirs(out_dir, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|\s]+', "_", str(filename or "chart"))[:40] or "chart"
        path = os.path.join(out_dir, f"{safe}.png")
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        return path
    except Exception:
        return ""
    finally:
        import matplotlib.pyplot as plt2

        plt2.close(fig)


def _fmt(v, unit=""):
    """图表数值标签格式化"""
    if v is None:
        return ""
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿{unit}"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.2f}万{unit}"
    if abs(v) >= 100:
        return f"{v:,.0f}{unit}"
    return f"{v:,.2f}".rstrip("0").rstrip(".") + str(unit or "")
