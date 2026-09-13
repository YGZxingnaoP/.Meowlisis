# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/comfy_connector/_patch_align.py
"""给 Impact-Pack 的 FaceDetailer 打「尺寸 16 对齐」补丁（幂等）。

背景：Anima(Cosmos Predict2) 的 PatchEmbed 要求 latent 的 H/W 能被 spatial_patch_size=2 整除，
      即**像素尺寸必须是 16 的倍数**。而 Impact-Pack 的 enhance_detail() 里
      crop 放大尺寸 new_w/new_h 只做了 int() 截断（无对齐），一旦出现 1752(=8*219) 这类
      "8 的倍数但不是 16 的倍数"，latent 就是 219 奇数 → 崩溃：
          H,W (219, 222) should be divisible by spatial_patch_size 2

修法：把 new_w/new_h（主路径 + max_size 裁剪分支 + force_inpaint 分支）对齐到 16 的倍数。
      Impact 采样后会把图 resize 回原始 crop 尺寸（core.py 末尾 tensor_resize(refined_image, w, h)），
      所以少几像素不会影响画质、也不影响贴回原图。
"""
import os

MARK = "[Meowlisis-align16]"
HELPER = (
    "\n# " + MARK + " Anima(Cosmos Predict2) 要求 latent H/W 为偶数 → crop 尺寸对齐 16 像素（幂等补丁）\n"
    "def _align16(v):\n"
    "    v = int(v)\n"
    "    v -= v % 16\n"
    "    return v if v >= 16 else 16\n\n\n"
)

ANCHOR = "def enhance_detail(image, model, clip, vae, guide_size, guide_size_for_bbox, max_size, bbox"

REPLACEMENTS = [
    # ① 主路径
    ("    new_w = int(w * upscale)\n    new_h = int(h * upscale)\n\n    # safeguard",
     "    new_w = int(w * upscale)\n    new_h = int(h * upscale)\n"
     "    new_w, new_h = _align16(new_w), _align16(new_h)  # " + MARK + "\n\n    # safeguard"),
    # ② max_size 裁剪分支
    ("        upscale *= max_size / max(new_w, new_h)\n"
     "        new_w = int(w * upscale)\n        new_h = int(h * upscale)\n",
     "        upscale *= max_size / max(new_w, new_h)\n"
     "        new_w = int(w * upscale)\n        new_h = int(h * upscale)\n"
     "        new_w, new_h = _align16(new_w), _align16(new_h)  # " + MARK + "\n"),
    # ③ force_inpaint 分支（直接用 crop 原尺寸时）
    ("            upscale = 1.0\n            new_w = w\n            new_h = h\n",
     "            upscale = 1.0\n            new_w = _align16(w)  # " + MARK + "\n"
     "            new_h = _align16(h)  # " + MARK + "\n"),
]


def core_path(node_dir):
    """Impact-Pack 的 core.py 路径（node_dir = .ComfyNode 目录；自动兼容两种布局）"""
    for base in (os.path.join(node_dir, "ComfyUI", "custom_nodes"),
                 os.path.join(node_dir, "custom_nodes")):
        p = os.path.join(base, "ComfyUI-Impact-Pack", "modules", "impact", "core.py")
        if os.path.isfile(p):
            return p
    return os.path.join(node_dir, "ComfyUI", "custom_nodes",
                        "ComfyUI-Impact-Pack", "modules", "impact", "core.py")


def apply(kernel_dir):
    """打入补丁（幂等）。返回 (ok, 说明)"""
    p = core_path(kernel_dir)
    if not os.path.isfile(p):
        return False, f"未找到 Impact-Pack core.py（跳过）: {p}"
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
    except Exception as e:
        return False, f"读取失败: {e}"
    if MARK in src:
        return True, "已打过 16 对齐补丁"

    orig = src
    applied, skipped = [], []
    for i, (old, new) in enumerate(REPLACEMENTS, start=1):
        if old in src:
            src = src.replace(old, new, 1)
            applied.append(i)
        else:
            skipped.append(i)
    if not applied:
        return False, "未匹配到任何补丁点（Impact 版本可能不同，请更新 _patch_align.py）"

    if ANCHOR in src:
        src = src.replace(ANCHOR, HELPER + ANCHOR, 1)
    else:
        return False, "未找到 enhance_detail 定义位置，放弃写入"

    try:
        bak = p + ".align16.bak"
        if not os.path.isfile(bak):
            with open(bak, "w", encoding="utf-8") as f:
                f.write(orig)
        with open(p, "w", encoding="utf-8") as f:
            f.write(src)
    except Exception as e:
        return False, f"写入失败: {e}"
    note = f"已打补丁（命中 {applied} 处"
    if skipped:
        note += f"，未命中 {skipped} 处"
    note += "）；重启绘画引擎后生效"
    return True, note


def is_patched(kernel_dir):
    """是否已打补丁"""
    p = core_path(kernel_dir)
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            return MARK in f.read()
    except Exception:
        return False
