# -*- coding: utf-8 -*-
# gui/tools/gen_card_jpg.py
r"""卡面压缩：cat_photos_png/*.png（832×1152，单张约 1.1MB）→ cat_photos_jpg/*.jpg（392×542）。

目录分工（resource/ 下）：
    cat_photos_png    白底原图（源，不参与加载，只给两个生成器当输入）
    cat_photos_jpg    不透明压缩版（392×542）—— 没 alpha 时的兜底
    cat_photos_alpha  抠像透明版（392×542 WebP）—— 主用，见 cutout_cards.py

为什么要做：
    主界面一次要挂 33 张卡面，原图总计约 75MB，最贵的不是下载（本地服务）而是解码 + 显存。
    而卡片在界面上最大只有 196×271 CSS px —— 2× 屏也就 392×542 设备像素，再大纯属浪费。

尺寸怎么定的：
    .slot 基准 136×188，最近那张 SCALE = 1.20×1.20 = 1.44 → 196×271 CSS px
    ×2（高 DPI）= 392×542 → 就是这里输出的尺寸。子卡 198×270 也吃这一套。

用法：
    python gui/tools/gen_card_jpg.py            # 只补缺的 / 过期的
    python gui/tools/gen_card_jpg.py --force    # 全部重转
    python gui/tools/gen_card_jpg.py --quality 88

注意：
    - PNG 原图【不删】，只新增 .jpg；前端 Cards.img() 优先用 .jpg，
      文件缺了会自动回退到 .png（orbit.js 的 onerror）。
    - 自己换了卡面 PNG 之后重跑一次即可（按 mtime 判断是否需要重转）。
"""

import argparse
import os
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent          # gui/
SRC_DIR = ROOT / 'resource' / 'cat_photos_png'         # 白底原图（源）
OUT_DIR = ROOT / 'resource' / 'cat_photos_jpg'         # 不透明压缩版
W, H = 392, 542


def convert(src: Path, quality: int) -> int:
    dst = OUT_DIR / (src.stem + '.jpg')
    im = Image.open(src)
    if im.mode != 'RGB':
        im = im.convert('RGB')
    # 卡面是满幅不透明图（72 张全是 RGB），不需要保留 alpha；
    # 圆角/裁切由 CSS 的 .face { overflow: hidden; border-radius } 负责。
    if im.size != (W, H):
        im = im.resize((W, H), Image.LANCZOS)
    im.save(dst, 'JPEG', quality=quality, optimize=True, progressive=True)
    return dst.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true', help='全部重转（默认只补缺/过期）')
    ap.add_argument('--quality', type=int, default=90, help='JPEG 质量，默认 90')
    args = ap.parse_args()

    if not SRC_DIR.is_dir():
        print('找不到源目录: %s' % SRC_DIR)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pngs = sorted(SRC_DIR.glob('*.png'))
    if not pngs:
        print('目录里没有 PNG: %s' % SRC_DIR)
        return 1

    done = skipped = 0
    total_src = total_dst = 0
    for src in pngs:
        dst = OUT_DIR / (src.stem + '.jpg')
        if (not args.force) and dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            skipped += 1
            total_src += src.stat().st_size
            total_dst += dst.stat().st_size
            continue
        try:
            n = convert(src, args.quality)
        except Exception as e:                       # 单张失败不影响整批
            print('  !! %s: %s' % (src.name, e))
            continue
        done += 1
        total_src += src.stat().st_size
        total_dst += n

    print('卡面压缩完成：转换 %d 张 / 跳过 %d 张（%d×%d, q=%d）'
          % (done, skipped, W, H, args.quality))
    if total_dst:
        print('体积：%.1f MB → %.1f MB（%.1f%%）'
              % (total_src / 1048576, total_dst / 1048576,
                 total_dst * 100.0 / total_src))
    return 0


if __name__ == '__main__':
    sys.exit(main())
