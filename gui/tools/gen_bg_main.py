#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""主界面背景图生成 —— 自动拉起本地内置 ComfyUI 出图，输出清晰原图。

★ 不做本地虚化：模糊是"显示时"做的（css/style.css 的 .bg-main 上 filter: blur(9px)）。
  这样原图保持清晰、以后想改虚化程度只改 CSS 一个数，不用重新生成。
  模糊放在"图"这一层几乎不花性能（层里没有动画，光栅化一次就缓存）；
  千万别把模糊加到 .container 上——那里面全是会动的卡片，会每帧重算 → 掉帧。

用法（从哪跑都行，脚本自己 chdir 到项目根）：
    D:\.Meowlisis\runtime\python.exe D:\.Meowlisis\gui\tools\gen_bg_main.py --check
    D:\.Meowlisis\runtime\python.exe D:\.Meowlisis\gui\tools\gen_bg_main.py
    ... --size 2560x1440          按你的屏幕分辨率出（默认 1920x1080）
    ... --seed 12345              固定种子，不满意就换
    ... --out  D:\...\main.jpg    自定义输出位置

输出： gui\resource\bg\main.jpg   （CSS 已按这个路径引用，生成完刷新页面即可）
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))          # D:\.Meowlisis
GUI = os.path.join(ROOT, "gui")
OUT_DIR = os.path.join(GUI, "resource", "bg")

# ============================ 提示词（要调就改这里） ============================
# 角色沿用卡面那套（白毛猫娘 / 黄眼 / 左侧蓝蝴蝶结 / JK），保证和卡片是同一只
CHARACTER = ("1girl, solo, catgirl, cat ears, cat tail, white hair, long curly white hair, "
             "yellow eyes, blue butterfly hair ornament on the left side of her hair, "
             "white blouse, JK uniform, pleated skirt")

# 明朗 + 偏粉：界面本来就是粉色系，背景基调要接得上（所以负向里把冷色/蓝绿主调压掉）
BRIGHT = ("bright cheerful atmosphere, soft pink dominant color palette, sakura pink, "
          "rose pink, cream white, warm golden sunlight, high key lighting, sunny, "
          "soft pink sky, cotton candy clouds, blooming cherry blossoms, petals in the air, "
          "sparkling, clean and airy, luminous, gentle pastel tones, adorable")

# 壁纸感 + 猫娘偏侧：位置偏但不留大白，整个画面是铺满的
COMPOSED = ("wide shot, full body, standing on the left third of the frame, "
            "off-center composition, scenery fills the whole frame, "
            "layered foreground and background, cherry blossom trees everywhere, "
            "soft depth of field, detailed background, cinematic anime wallpaper")

QUALITY = ("masterpiece, very aesthetic, best quality, score_9, score_8_up, score_7_up, "
           "highres, absurdres, anime wallpaper, official art, cute anime illustration, "
           "kawaii, soft pastel palette, gentle shading, clean crisp lineart")

POSITIVE = ", ".join([QUALITY, CHARACTER, BRIGHT, COMPOSED])
NEGATIVE = ("dark, gloomy, night, shadow, dark background, moody, desaturated, dull, "
            "cold colors, blue dominant, teal dominant, green dominant, "
            "empty background, large empty space, blank space, plain flat background, "
            "centered composition, symmetrical composition, close-up, portrait, "
            "cropped, cut off, 2girls, multiple girls, crowd, extra people, "
            "text, watermark, signature, logo, letters, lowres, jpeg artifacts, "
            "realistic, photorealistic, 3d, messy, cluttered")
# ==============================================================================


def parse_size(s):
    try:
        w, h = str(s).lower().split("x")
        return int(w), int(h)
    except Exception:
        raise argparse.ArgumentTypeError("尺寸格式应为 宽x高，例如 1920x1080")


def gen_size(W, H, cap=1152):
    """出图尺寸：按目标比例、长边不超过 cap、且 16 对齐。
    大分辨率直接画容易出双人/糊结构，所以先出中小图再放大 —— 反正界面还要模糊。"""
    sc = min(1.0, float(cap) / max(W, H))
    gw, gh = int(W * sc) // 16 * 16, int(H * sc) // 16 * 16
    return max(256, gw), max(256, gh)


def main():
    ap = argparse.ArgumentParser(description="主界面背景图（自动启动本地 ComfyUI）")
    ap.add_argument("--size", type=parse_size, default=(1920, 1080), help="最终尺寸，默认 1920x1080")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "main.jpg"), help="输出文件")
    ap.add_argument("--gen", type=parse_size, default=None, help="出图尺寸，默认按比例自动")
    ap.add_argument("--blur", type=float, default=0, help="本地预虚化半径，默认 0（模糊交给显示层）")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--base", default=None, help="ComfyUI 地址，如 http://127.0.0.1:8188")
    ap.add_argument("--no-start", action="store_true", help="引擎已在跑，不想动它")
    ap.add_argument("--keep-raw", action="store_true", help="把 ComfyUI 原图另存一份")
    ap.add_argument("--check", action="store_true", help="只检查引擎/配置，不启动不生成")
    ap.add_argument("--dry", action="store_true", help="只打印提示词，不生成")
    args = ap.parse_args()

    W, H = args.size
    gw, gh = args.gen or gen_size(W, H)
    print("最终尺寸: %dx%d    出图尺寸: %dx%d    本地预虚化: %s" % (W, H, gw, gh, args.blur or "无"))
    print("\n正向提示词:\n  " + POSITIVE)
    print("\n负向提示词:\n  " + NEGATIVE)
    print("\n输出: %s" % args.out)
    if args.dry:
        return 0

    # 项目模块按 CWD 找 config.yml / .ComfyNode，所以必须先 chdir 再 import
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    from func.toolbox.flux_painter.config import TBFluxPainterConfig
    from func.toolbox.flux_painter.comfy_connector.comfy_painter import get_managed_painter

    cfg = TBFluxPainterConfig()
    if args.base:
        from urllib.parse import urlparse
        u = urlparse(args.base if "://" in args.base else "http://" + args.base)
        cfg.comfy_host = u.hostname or "127.0.0.1"
        cfg.comfy_port = int(u.port or 8188)
    painter = get_managed_painter(cfg)
    print("\n引擎地址: %s   模式: %s" % (cfg.comfy_base(), cfg.comfy_mode))

    if args.check:
        from func.toolbox.flux_painter.comfy_connector.base import ANIMA_UNET, ANIMA_CLIP, ANIMA_VAE
        kern = os.path.join(cfg.comfy_node_dir, "ComfyUI", "main.py")
        print("  引擎在线   = %s" % painter.health())
        print("  内置内核   = %s (%s)" % (kern, os.path.isfile(kern)))
        print("  内置解释器 = %s (%s)" % (cfg.internal_python, os.path.isfile(cfg.internal_python or "")))
        print("  采样       = steps=%s cfg=%s %s/%s" %
              (cfg.sampler_steps, cfg.sampler_cfg, cfg.sampler_name, cfg.sampler_scheduler))
        print("  模型自检（缺哪个就出不了图）:")
        for sub, name in (("diffusion_models", ANIMA_UNET), ("text_encoders", ANIMA_CLIP), ("vae", ANIMA_VAE)):
            p = os.path.join(cfg.comfy_node_dir, "models", sub, name)
            print("    %-16s %-38s %s" % (sub, name, "OK" if os.path.isfile(p) else "缺失!"))
        return 0

    # ---------- 1. 引擎 ----------
    if painter.health():
        print("引擎已在运行，直接复用（不动现有服务）")
    elif args.no_start:
        print("引擎没在跑，且指定了 --no-start：退出。")
        return 2
    else:
        if cfg.comfy_mode == "external":
            print("  注意：config.yml 是 external 模式（不管理进程）；这里仍用内置引擎把它拉起来，")
            print("        两者共用同一个 host:port，起来后照常可用。")
        print("正在拉起本地内置 ComfyUI（首次可能 1~2 分钟）...")
        ok, msg = painter.start()
        print("  " + str(msg))
        if not ok:
            print("\n启动失败。8188 被占用一般是：")
            print("  · AutoDL 的 SSH 隧道（ssh -L 8188:...）开着 —— 先关隧道，或 --base 指向云端那台；")
            print("  · 或手动开着的 D:\\ComfyUI 完整版 —— 先关掉它。")
            return 2

    # ---------- 2. 生成 ----------
    graph = painter.build_graph(POSITIVE, NEGATIVE, gw, gh,
                                seed=args.seed, prefix="bg_main", steps=args.steps)
    ok, pid, err = painter.submit(graph)
    if not ok:
        print("提交失败: " + str(err))
        return 3
    print("已提交 prompt_id=%s，等待生成..." % pid)
    t0 = time.time()
    ok, images, err = painter.wait(pid, timeout=900,
                                   on_event=lambda s: print("  " + str(s), flush=True))
    if not ok or not images:
        print("生成失败: " + str(err))
        return 4
    paths = painter.images_local(images)
    if not paths:
        print("拿不到输出文件")
        return 5
    raw = paths[0]
    print("原图: %s  (%.1fs)" % (raw, time.time() - t0))

    # ---------- 3. 后处理：只做 cover 缩放到最终尺寸（不虚化，模糊交给显示层） ----------
    from PIL import Image, ImageEnhance
    img = Image.open(raw).convert("RGB")
    sc = max(W / img.width, H / img.height)
    if sc != 1:
        img = img.resize((max(1, round(img.width * sc)), max(1, round(img.height * sc))), Image.LANCZOS)
    left, top = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((left, top, left + W, top + H))
    img = ImageEnhance.Color(img).enhance(1.06)        # 再提一点鲜艳度，压上去之后依然明朗
    img = ImageEnhance.Brightness(img).enhance(1.03)
    if args.blur and args.blur > 0:
        from PIL import ImageFilter
        img = img.filter(ImageFilter.GaussianBlur(radius=float(args.blur)))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    img.save(args.out, "JPEG", quality=93, optimize=True)
    print("已写出: %s  (%d KB)" % (args.out, os.path.getsize(args.out) // 1024))
    if args.keep_raw:
        import shutil
        keep = os.path.splitext(args.out)[0] + "_raw.png"
        shutil.copyfile(raw, keep)
        print("原图已留: %s" % keep)
    print("\n界面已按 resource/bg/main.jpg 引用，Ctrl+F5 刷新即可看到（模糊在 CSS 里）。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
