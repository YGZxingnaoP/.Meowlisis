# -*- coding: utf-8 -*-
"""养猪游戏：卡片渲染（HTML → PNG）。

零新依赖：用系统自带的 Edge / Chrome 无头模式截图，再用 Pillow 裁掉空白。

数据格式（字段都可省）：
    {
      "img":      "assets/scene_farm.png",   # 图片位：相对插件根目录 / 绝对路径 / data:URI
      "title":    "🐷 打卡成功",
      "badge":    "+60 金币",
      "subtitle": "第 12 天 · 渔家傲",
      "stats":    [{"k": "金币", "v": "280"}, ...],   # 数值，建议 ≤4
      "rows":     [{"name": "1. 其乐容容", "v": "31 只"}, ...],   # 榜单，建议 ≤6
      "lines":    ["· 猪猪游戏 打卡", {"h": "标题行"}],          # 菜单/规则
      "tip":      "鱼猪 3 天不换水就消失，它只是想被在乎。",
    }

用法：
    from .poster import make_card
    make_card(data, "poster/out/x.png")
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # 插件根目录（assets/ 的父目录）
TEMPLATE = os.path.join(HERE, "template.html")

WIDTH = 720          # 逻辑宽度
HEIGHT = 1400        # 画布高度上限（渲染后按内容裁掉）
SCALE = 2            # 2 倍图
BANNER = (700, 300)  # 卡片横幅逻辑尺寸
BANNER_PX = (1400, 600)   # 横幅出图尺寸（SCALE 倍）
CARD_FALLBACK = "card.png"  # 素材缺失时的兜底图（插件卡面）


def crop_cover(path, size):
    """居中裁剪到目标比例并缩放，返回 JPEG bytes；失败返回 None。

    素材比例和版面不一致时一律「裁」，绝不拉伸变形。
    """
    try:
        import io

        from PIL import Image
        im = Image.open(path).convert("RGB")
        tw, th = int(size[0]), int(size[1])
        tr = tw / float(th)
        sr = im.width / float(im.height)
        if sr > tr:                        # 太宽 → 裁左右
            nw = int(round(im.height * tr))
            x = (im.width - nw) // 2
            im = im.crop((x, 0, x + nw, im.height))
        elif sr < tr:                      # 太高 → 裁上下
            nh = int(round(im.width / tr))
            y = (im.height - nh) // 2
            im = im.crop((0, y, im.width, y + nh))
        if im.size != (tw, th):
            im = im.resize((tw, th), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        return buf.getvalue()
    except Exception:
        return None



def find_browser():
    """找一个能无头截图的内核（Edge 优先）。"""
    cands = [
        os.environ.get("PIG_BROWSER") or "",
        shutil.which("msedge") or "",
        shutil.which("chrome") or "",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return ""


def _inline_img(data, base_dir):
    """把图片读成 data:URI（裁到横幅比例 → JPEG → base64），HTML 自包含。

    缺图回退插件卡面 card.png；连卡面都没有才不显示图片位。
    """
    d = dict(data or {})
    img = str(d.get("img") or "")
    path = ""
    if img and not img.startswith(("data:", "http://", "https://")):
        p = img if os.path.isabs(img) else os.path.join(base_dir or ROOT, img)
        if os.path.isfile(p):
            path = p
    if not path:
        path = os.path.join(ROOT, CARD_FALLBACK)          # 兜底卡面
    if not os.path.isfile(path):
        d["img"] = ""
        return d
    blob = crop_cover(path, BANNER_PX)                    # 尺寸不对 → 居中裁
    if blob:
        d["img"] = "data:image/jpeg;base64," + base64.b64encode(blob).decode()
        return d
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/" + ext
    with open(path, "rb") as f:
        d["img"] = "data:%s;base64,%s" % (mime, base64.b64encode(f.read()).decode())
    return d


def build_html(data, template=None, base_dir=None):
    """把结构化数据填进模板（模板只认 __DATA__ 这一个占位符）。"""
    with open(template or TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    payload = json.dumps(_inline_img(data, base_dir), ensure_ascii=False)
    return html.replace("__DATA__", payload)


def _shoot(html, out_png, width=WIDTH, height=HEIGHT):
    """无头截图 → 裁边 → 白底 PNG（临时文件全部清掉）。"""
    browser = find_browser()
    if not browser:
        raise RuntimeError("找不到 Edge / Chrome，可用环境变量 PIG_BROWSER 指定路径")

    tmp = tempfile.mkdtemp(prefix="pigposter_")
    try:
        html_path = os.path.join(tmp, "card.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        raw = os.path.join(tmp, "shot.png")
        subprocess.run([
            browser,
            "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--disable-sync",
            "--user-data-dir=" + os.path.join(tmp, "profile"),
            "--default-background-color=00000000",
            "--force-device-scale-factor=%d" % SCALE,
            "--window-size=%d,%d" % (width, height),
            "--virtual-time-budget=1500",
            "--screenshot=" + raw,
            "file:///" + html_path.replace("\\", "/"),
        ], timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not os.path.isfile(raw):
            raise RuntimeError("浏览器没有产出截图")
        _trim(raw, out_png)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_png


def _trim(raw_png, out_png):
    """裁掉四周空白（透明部分），并合到白底上。"""
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    try:
        from PIL import Image
    except Exception:
        shutil.copyfile(raw_png, out_png)
        return out_png

    im = Image.open(raw_png).convert("RGBA")
    box = im.getbbox()
    if box and (box[2] - box[0]) * (box[3] - box[1]) < 0.97 * im.width * im.height:
        pad = 8 * SCALE
        box = (max(0, box[0] - pad), max(0, box[1] - pad),
               min(im.width, box[2] + pad), min(im.height, box[3] + pad))
        im = im.crop(box)

    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, mask=im.split()[3])
    bg.save(out_png)
    return out_png


def make_card(data, out_png, base_dir=None, height=HEIGHT, template=None):
    """一步到位：数据 → HTML → PNG。返回图片路径。"""
    html = build_html(data, template, base_dir)
    return _shoot(html, out_png, height=height)


def preview(data, out_png, keep_html=None, base_dir=None, height=HEIGHT):
    """调试用：顺带把 HTML 落盘，浏览器里直接看排版。"""
    html = build_html(data, None, base_dir)
    if keep_html:
        os.makedirs(os.path.dirname(os.path.abspath(keep_html)), exist_ok=True)
        with open(keep_html, "w", encoding="utf-8") as f:
            f.write(html)
    return _shoot(html, out_png, height=height)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("插件根目录：", ROOT)
    print("浏览器：", find_browser() or "（没找到）")
