# -*- coding: utf-8 -*-
# gui/tools/cutout_cards.py
r"""卡面抠像：把白底插画的白色画布挖成透明，角色像素原样保留。

为什么必须"抠"而不是"调透明度"：
    卡片看起来是白底，是因为 resource/cat_photos_png/*.png 就是【白底插画】
    （实测边框 72~86% 是近白）。直接给整张图加透明度 → 角色也跟着变淡。
    只有把背景真的挖掉，角色才能保持 100% 不透明地"浮"在壁纸上。

为什么不直接用"亮度阈值当 alpha"：
    会把角色身上的白（白发 / 白衬衫 / 白猫）一起吃掉，还会留一圈白边（光晕）。
做法（顺序很重要）：
    1) 泛洪：从画布【边框】向内，只吃"与边缘连通的近白像素" →
       角色内部的白（帽子/衣服/玩偶）因为不和边框连通，一律保留；
    2) 反预乘去白边：边界上观测色 C = a·F + (1−a)·白  →  F = (C − (1−a)·255) / a；
       不做这一步，角色轮廓会留一圈灰白描边；
    3) 羽化 alpha 1px，藏掉锯齿；
    4) ★ 先抠 832×1152 原图，再【预乘 alpha】降采样到目标尺寸 ——
       直接缩放带 alpha 的图会在边缘把白色混进来（Pillow 不预乘）。

输出：
    <out>/<id>.webp   带 alpha 的 WebP（libwebp，alpha 无损，体积约 PNG 的 1/5）
    <out>/<id>.png    可选（--png），质量基准对照用

用法：
    python gui/tools/cutout_cards.py --only llm,catbrain     # 只重抠几张（调试用）
    python gui/tools/cutout_cards.py                        # 全部 → resource/cat_photos_alpha
    ... --width 392     输出宽（默认 392 = 196 CSS px × 2 倍屏）；想更清晰可给 588 / 784
    ... --thr 238       近白判定阈值（min(R,G,B) ≥ thr 视为候选背景）
    ... --keep 0.3      背景保留多少不透明度（0=全透明，0.3=半透明白底）
    ... --png           额外输出 PNG 对照（体积约为 WebP 的 5 倍）
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
GUI = HERE.parent
SRC_DIR = GUI / 'resource' / 'cat_photos_png'      # 白底原图（832×1152）
OUT_DIR = GUI / 'resource' / 'cat_photos_alpha'    # 抠像透明版（392×542 WebP）

FFMPEG_CANDIDATES = [
    os.environ.get('FLUXPAINTER_FFMPEG', ''),
    r'D:\FFmpeg\ffmpeg-8.0-full_build\bin\ffmpeg.exe',
    r'D:\.Meowlisis\.vendor\.RVC\ffmpeg.exe',
    'ffmpeg',
]


def find_ffmpeg():
    for p in FFMPEG_CANDIDATES:
        if not p:
            continue
        if os.path.isfile(p) or p == 'ffmpeg':
            try:
                r = subprocess.run([p, '-hide_banner', '-encoders'],
                                   capture_output=True, text=True, timeout=20)
                if 'libwebp' in (r.stdout or ''):
                    return p
            except Exception:
                continue
    return None


def fill_background(rgb, thr):
    """从边框泛洪，返回 (背景掩码, 近白像素总数)。只吃和画布边缘连通的近白像素。"""
    h, w = rgb.shape[:2]
    near_white = rgb.min(axis=2) >= thr
    bg = np.zeros((h, w), dtype=bool)

    # 种子：四条边框上的近白像素
    seeds = []
    for x in range(w):
        if near_white[0, x]:
            seeds.append(x)
        if near_white[h - 1, x]:
            seeds.append((h - 1) * w + x)
    for y in range(h):
        if near_white[y, 0]:
            seeds.append(y * w)
        if near_white[y, w - 1]:
            seeds.append(y * w + w - 1)

    flat_bg = bg.reshape(-1)
    flat_nw = near_white.reshape(-1)
    stack = list(seeds)
    while stack:
        i = stack.pop()
        if flat_bg[i]:
            continue
        flat_bg[i] = True
        x = i % w
        y = i // w
        if x > 0 and flat_nw[i - 1] and not flat_bg[i - 1]:
            stack.append(i - 1)
        if x + 1 < w and flat_nw[i + 1] and not flat_bg[i + 1]:
            stack.append(i + 1)
        if y > 0 and flat_nw[i - w] and not flat_bg[i - w]:
            stack.append(i - w)
        if y + 1 < h and flat_nw[i + w] and not flat_bg[i + w]:
            stack.append(i + w)
    return bg, int(near_white.sum())


def cutout(im, thr=238, feather=1.0, keep=0.0):
    """返回 RGBA（原尺寸）。keep = 背景保留的不透明度（0 全透明）。"""
    rgba = np.array(im.convert('RGBA'), dtype=np.float32)
    rgb = rgba[:, :, :3]
    bg, _ = fill_background(rgb, thr)

    # alpha：背景 keep，前景 1
    alpha = np.ones(bg.shape, dtype=np.float32)
    if keep > 0:
        alpha[bg] = keep
    else:
        alpha[bg] = 0.0

    # 反预乘去白边：只对"半透明像素"做（纯背景/纯前景不动）
    if keep <= 0:
        a = alpha
        edge = (a > 0.01) & (a < 0.995)
        if edge.any():
            ae = a[edge][:, None]
            ce = rgb[edge]
            fixed = (ce - (1.0 - ae) * 255.0) / np.maximum(ae, 0.05)
            rgb[edge] = np.clip(fixed, 0, 255)

    rgba[:, :, :3] = rgb
    rgba[:, :, 3] = alpha * 255.0
    out = Image.fromarray(rgba.clip(0, 255).astype(np.uint8), 'RGBA')

    # 羽化 alpha（只模糊透明通道，颜色不动）
    if feather and feather > 0:
        a_im = out.getchannel('A').filter(ImageFilter.GaussianBlur(feather))
        out.putalpha(a_im)
    return out


def resize_premultiplied(im, width):
    """带 alpha 的缩放：先预乘再缩，最后反预乘，避免边缘掺白（Pillow 不预乘）。
    高度按卡面标准比例 392:542 算（源图 832×1152 正好落在这里），
    这样 cat_photos_alpha 和 cat_photos_jpg 的尺寸严格一致。"""
    if im.width == width and im.height == round(width * 542 / 392):
        return im
    h = max(1, round(width * 542 / 392))
    arr = np.array(im, dtype=np.float32)
    a = arr[:, :, 3:4] / 255.0
    pre = np.concatenate([arr[:, :, :3] * a, arr[:, :, 3:4]], axis=2)
    pim = Image.fromarray(np.clip(pre, 0, 255).astype(np.uint8), 'RGBA').resize((width, h), Image.LANCZOS)
    parr = np.array(pim, dtype=np.float32)
    pa = parr[:, :, 3:4] / 255.0
    rgb = np.clip(parr[:, :, :3] / np.maximum(pa, 1e-3), 0, 255)
    out = np.concatenate([rgb, parr[:, :, 3:4]], axis=2)
    return Image.fromarray(out.clip(0, 255).astype(np.uint8), 'RGBA')


def to_webp(ffmpeg, png_path, webp_path, quality=88):
    """PNG(RGBA) → WebP。注意 ffmpeg 的 libwebp 只认这几个 AVOption：
    -lossless / -quality / -preset / -cr_threshold / -cr_size
    （没有 -alpha_quality、-compression_level，写了会直接报参数错）。
    pix_fmt 用 bgra：不让色度再降采样，抠像的边缘更干净。"""
    cmd = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
           '-i', str(png_path),
           '-c:v', 'libwebp', '-lossless', '0',
           '-quality', str(quality), '-preset', 'picture',
           '-pix_fmt', 'bgra',
           str(webp_path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not os.path.isfile(webp_path):
        raise RuntimeError('ffmpeg 失败: ' + (r.stderr or '')[-300:])


def main():
    ap = argparse.ArgumentParser(description='卡面抠像（白底 → 透明）')
    ap.add_argument('--only', default='', help='只处理这些 id（逗号分隔），空=全部')
    ap.add_argument('--out', default=str(OUT_DIR), help='输出目录，默认 resource/cat_photos_alpha')
    ap.add_argument('--width', type=int, default=392, help='输出宽度，默认 392（196 CSS px × 2 倍屏）')
    ap.add_argument('--thr', type=int, default=238, help='近白阈值，默认 238')
    ap.add_argument('--feather', type=float, default=1.0, help='alpha 羽化半径（原图像素），默认 1.0')
    ap.add_argument('--keep', type=float, default=0.0, help='背景保留不透明度，0=全透明')
    ap.add_argument('--q', type=int, default=88, help='WebP 质量，默认 88')
    ap.add_argument('--png', action='store_true', help='额外输出 PNG（对照质量/体积）')
    ap.add_argument('--no-webp', action='store_true', help='只出 PNG')
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ids = [s.strip() for s in args.only.split(',') if s.strip()]
    if ids:
        srcs = [SRC_DIR / (i + '.png') for i in ids]
        missing = [str(p) for p in srcs if not p.is_file()]
        if missing:
            print('找不到源图:', ', '.join(missing))
            return 2
    else:
        srcs = sorted(SRC_DIR.glob('*.png'))
    if not srcs:
        print('没有源 PNG:', SRC_DIR)
        return 2

    ffmpeg = None if args.no_webp else find_ffmpeg()
    if not args.no_webp and not ffmpeg:
        print('!! 找不到带 libwebp 的 ffmpeg，退化为只出 PNG')
        args.no_webp = True

    print('源图 %d 张 → %s  宽=%d thr=%d feather=%.2f keep=%.2f'
          % (len(srcs), out_dir, args.width, args.thr, args.feather, args.keep))
    tmpdir = Path(tempfile.mkdtemp(prefix='cutout_'))
    total_png = total_webp = 0
    bad = []
    for src in srcs:
        try:
            im = Image.open(src)
            cut = cutout(im, thr=args.thr, feather=args.feather, keep=args.keep)
            small = resize_premultiplied(cut, args.width)
            tmp_png = tmpdir / (src.stem + '.png')
            small.save(tmp_png, 'PNG', optimize=True)
            total_png += tmp_png.stat().st_size
            # 透明比例（判断抠得像不像：太低说明这张背景不是白/阈值太严）
            arr = np.array(small, dtype=np.uint8)
            trans = float((arr[:, :, 3] < 12).mean())
            if trans < 0.08:
                bad.append(src.stem + '(%.0f%%)' % (trans * 100))
            if args.png:
                small.save(out_dir / (src.stem + '.png'), 'PNG', optimize=True)
            if not args.no_webp:
                dst = out_dir / (src.stem + '.webp')
                to_webp(ffmpeg, tmp_png, dst, args.q)
                total_webp += dst.stat().st_size
            else:
                small.save(out_dir / (src.stem + '.png'), 'PNG', optimize=True)
            print('  %-22s 透明占比 %3.0f%%' % (src.stem, trans * 100))
        except Exception as e:
            print('  !! %s: %s' % (src.stem, e))

    n = len(srcs)
    print('\n完成 %d 张' % n)
    if not args.no_webp:
        print('WebP 合计 %.1f MB（平均 %.0f KB/张）' % (total_webp / 1048576, total_webp / n / 1024))
    if args.png:
        print('PNG  合计 %.1f MB（平均 %.0f KB/张）' % (total_png / 1048576, total_png / n / 1024))
    if bad:
        print('⚠️ 透明比例偏低（可能不是纯白底 / 阈值需要调 --thr）:')
        print('   ' + ', '.join(bad[:20]) + (' …' if len(bad) > 20 else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
