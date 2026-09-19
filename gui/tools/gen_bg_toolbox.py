#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""工具箱（Toolbox）界面背景图生成 —— 和 gen_bg_main.py 同一套机制，只是目标不同。

★ 不做本地虚化：模糊是"显示时"做的（css/orbit.css 的 .toolbox-panel::before 上 filter: blur(7px)）。
  原图保持清晰，想改虚化程度只改 CSS。

尺寸默认 1180x800 —— 就是 .toolbox-panel 的实际尺寸（css/orbit.css）。
猫娘放在画面右侧（工具箱面板内的卡片是绕中心排的，中间要留干净），色调同样要求明朗。

用法：
    D:\.Meowlisis\runtime\python.exe D:\.Meowlisis\gui\tools\gen_bg_toolbox.py --check
    D:\.Meowlisis\runtime\python.exe D:\.Meowlisis\gui\tools\gen_bg_toolbox.py
    ... --size 1400x950 --seed 777

输出： gui\resource\bg\toolbox.jpg
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
GUI = os.path.join(ROOT, "gui")
OUT_DIR = os.path.join(GUI, "resource", "bg")

# ============================ 提示词（要调就改这里） ============================
CHARACTER = ("1girl, solo, catgirl, cat ears, cat tail, white hair, long curly white hair, "
             "yellow eyes, blue butterfly hair ornament on the left side of her hair, "
             "white blouse, JK uniform, pleated skirt")

BRIGHT = ("bright cheerful atmosphere, high key lighting, sunny daylight, warm golden light, "
          "soft pink and gold color accents, sparkling magical glow, vivid colors, "
          "clean and airy, luminous, cozy and warm, adorable")

# 工具箱这张：猫娘回中间，双手打开闪光的宝箱
COMPOSED = ("1girl in the center of the frame, full body, centered composition, "
            "opening a large treasure chest in front of her with both hands, "
            "the chest glowing brightly, sparkling treasure, gold coins and jewels "
            "spilling out, magical light rays, sparkles everywhere, "
            "wide shot, bright cozy room, soft depth of field, cinematic anime wallpaper")

QUALITY = ("masterpiece, very aesthetic, best quality, score_9, score_8_up, score_7_up, "
           "highres, absurdres, anime wallpaper, official art, cute anime illustration, "
           "kawaii, soft pastel palette, gentle shading, clean crisp lineart")

POSITIVE = ", ".join([QUALITY, CHARACTER, BRIGHT, COMPOSED])
# 注意：这张要"居中"，所以负向里不能像主界面那样压 centered / symmetrical
NEGATIVE = ("dark, gloomy, night, shadow, dark background, moody, desaturated, dull, "
            "off-center composition, close-up, portrait, "
            "cropped, cut off, 2girls, multiple girls, crowd, extra people, "
            "text, watermark, signature, logo, letters, lowres, jpeg artifacts, "
            "realistic, photorealistic, 3d, messy, cluttered")
# ==============================================================================


def parse_size(s):
    try:
        w, h = str(s).lower().split("x")
        return int(w), int(h)
    except Exception:
        raise argparse.ArgumentTypeError("尺寸格式应为 宽x高，例如 1180x800")


def gen_size(W, H, cap=1152):
    """出图尺寸：按目标比例、长边不超过 cap、且 16 对齐（引擎要求 16 的倍数）"""
    sc = min(1.0, float(cap) / max(W, H))
    gw, gh = int(W * sc) // 16 * 16, int(H * sc) // 16 * 16
    return max(256, gw), max(256, gh)


def main():
    ap = argparse.ArgumentParser(description="工具箱界面背景图（自动启动本地 ComfyUI）")
    ap.add_argument("--size", type=parse_size, default=(1180, 800),
                    help="最终尺寸，默认 1180x800（= .toolbox-panel 尺寸）")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "toolbox.jpg"), help="输出文件")
    ap.add_argument("--gen", type=parse_size, default=None, help="出图尺寸，默认按比例自动")
    ap.add_argument("--blur", type=float, default=0, help="本地预虚化半径，默认 0（模糊交给显示层）")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--base", default=None, help="ComfyUI 地址")
    ap.add_argument("--no-start", action="store_true")
    ap.add_argument("--keep-raw", action="store_true")
    ap.add_argument("--check", action="store_true", help="只检查引擎/配置")
    ap.add_argument("--dry", action="store_true", help="只打印提示词")
    args = ap.parse_args()

    W, H = args.size
    gw, gh = args.gen or gen_size(W, H)
    print("最终尺寸: %dx%d    出图尺寸: %dx%d    本地预虚化: %s" % (W, H, gw, gh, args.blur or "无"))
    print("\n正向提示词:\n  " + POSITIVE)
    print("\n负向提示词:\n  " + NEGATIVE)
    print("\n输出: %s" % args.out)
    if args.dry:
        return 0

    os.chdir(ROOT)                      # 项目模块按 CWD 找 config.yml / .ComfyNode
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
            print("  · AutoDL 的 SSH 隧道开着 —— 先关隧道，或 --base 指向云端那台；")
            print("  · 或手动开着的 D:\\ComfyUI 完整版 —— 先关掉它。")
            return 2

    graph = painter.build_graph(POSITIVE, NEGATIVE, gw, gh,
                                seed=args.seed, prefix="bg_toolbox", steps=args.steps)
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

    from PIL import Image, ImageEnhance
    img = Image.open(raw).convert("RGB")
    sc = max(W / img.width, H / img.height)
    if sc != 1:
        img = img.resize((max(1, round(img.width * sc)), max(1, round(img.height * sc))), Image.LANCZOS)
    left, top = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((left, top, left + W, top + H))
    img = ImageEnhance.Color(img).enhance(1.06)
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
    print("\n界面已按 resource/bg/toolbox.jpg 引用，Ctrl+F5 刷新即可看到。")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
