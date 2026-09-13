# -*- coding: utf-8 -*-
# scripts/check_brightness.py
"""出图亮度体检：按时间排序统计每张图的亮度分布，用来判断"画布是不是普遍变暗了"。

跑法（项目根目录）：
    runtime\\python.exe scripts\\check_brightness.py                 # 只扫 .ComfyNode/output（非递归）
    runtime\\python.exe scripts\\check_brightness.py --paint        # 加上 character/paints 归档图
    runtime\\python.exe scripts\\check_brightness.py --dir 某目录 --recursive
    runtime\\python.exe scripts\\check_brightness.py --limit 40      # 只看最近 40 张

指标：
    平均亮度  0~100（越大越亮）
    中位亮度  0~100
    暗部占比  亮度 < 20% 的像素比例（%）
    高光占比  亮度 > 90% 的像素比例（%）
    对比度    亮度标准差（越大反差越强）
"""
import argparse
import glob
import os
import sys

try:
    from PIL import Image
    import numpy as np
except Exception as e:                                  # pragma: no cover
    print("需要 PIL + numpy：", e)
    sys.exit(1)


def stats(path, side=256):
    """返回 (mean, median, dark_ratio, bright_ratio, std)，单位 0~100 / %"""
    try:
        with Image.open(path) as im:
            g = im.convert("L")
            if max(g.size) > side:
                g = g.resize((side, side), Image.BILINEAR)
            a = np.asarray(g, dtype=np.float32) / 255.0
    except Exception:
        return None
    return (a.mean() * 100.0, float(np.median(a)) * 100.0,
            float((a < 0.20).mean() * 100.0), float((a > 0.90).mean() * 100.0),
            a.std() * 100.0)


def collect(args):
    files = []
    base = args.dir
    pat = "**/*.png" if args.recursive else "*.png"
    files += glob.glob(os.path.join(base, pat), recursive=args.recursive)
    if args.jpg:
        patj = "**/*.jpg" if args.recursive else "*.jpg"
        files += glob.glob(os.path.join(base, patj), recursive=args.recursive)
    if args.paint:
        files += glob.glob(os.path.join("character", "paints", "*", "image.png"))
    if args.exclude:
        ex = [x.strip().lower() for x in args.exclude.split(",") if x.strip()]
        files = [f for f in files if not any(k in os.path.basename(f).lower() for k in ex)]
    files = [f for f in files if os.path.isfile(f)]
    files.sort(key=os.path.getmtime)
    if args.limit:
        files = files[-args.limit:]
    return files


def main():
    ap = argparse.ArgumentParser(description="出图亮度体检")
    ap.add_argument("--dir", default=os.path.join(".ComfyNode", "output"))
    ap.add_argument("--recursive", action="store_true")
    ap.add_argument("--paint", action="store_true", help="同时统计 character/paints 归档图")
    ap.add_argument("--jpg", action="store_true", help="同时统计 .jpg")
    ap.add_argument("--exclude", default="pro_dump", help="文件名包含这些词的跳过（逗号分隔）")
    ap.add_argument("--limit", type=int, default=0, help="只看最近 N 张")
    args = ap.parse_args()

    files = collect(args)
    if not files:
        print("没找到图片。检查 --dir 或加 --paint。")
        return 1

    print(f"{'#':>3}  {'time':16}  {'mean':>6} {'median':>6} {'dark<20':>7} {'hi>90':>6} "
          f"{'std':>6}  file")
    print("-" * 110)
    rows = []
    for i, f in enumerate(files, 1):
        st = stats(f)
        if not st:
            continue
        import time
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(f)))
        rows.append((i, ts, st, f))
        print(f"{i:>3}  {ts:16}  {st[0]:6.1f} {st[1]:6.1f} {st[2]:7.1f} {st[3]:6.1f} "
              f"{st[4]:6.1f}  {os.path.relpath(f)}")

    if len(rows) >= 6:
        half = len(rows) // 2
        old = [r[2][0] for r in rows[:half]]
        new = [r[2][0] for r in rows[half:]]
        print("-" * 110)
        print(f"前 {len(old)} 张 平均亮度 = {sum(old)/len(old):.1f}")
        print(f"后 {len(new)} 张 平均亮度 = {sum(new)/len(new):.1f}     "
              f"差值 = {sum(new)/len(new) - sum(old)/len(old):+.1f}")
        darkest = min(rows, key=lambda r: r[2][0])
        print(f"最暗：#{darkest[0]} {darkest[1]} mean={darkest[2][0]:.1f}  "
              f"{os.path.relpath(darkest[3])}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
