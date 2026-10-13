# -*- coding: utf-8 -*-
# scripts/paint.py
r"""模拟触发画图工具（flux_paint）—— 等价于 QQ/主程序里 AI 决定调用画图工具的那一下。

不做任何"自己拼提示词"的事：只把一句**自然语言需求**丢给工具入口，
后面全部走生产链路：
    TBFluxPainterCore.dispatch("flux_paint", {"request": 需求})
      → 真 LLM 出词（法典 + function calling）
      → 真 Pro 渲染（模型放大 + 分块重绘 + 局部细化）
      → 真归档 → 真审查 → 真写记忆

产物：
    <项目根>/character/paints/<时间>_<标题>/image.png   生产归档（原始位置）
    <本目录>/paint_<时间戳>.png                          复制到这里的成品图
    <本目录>/paint_<时间戳>.txt                          本次需求 / 参数 / 完整 positive

用法：
    双击 paint.bat      或者      runtime\311\python.exe scripts\paint.py
"""

import datetime
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))      # scripts/
ROOT = os.path.dirname(HERE)                           # 项目根
sys.path.insert(0, ROOT)
os.chdir(ROOT)          # 生产代码大量用相对路径，必须切到项目根

SAVE_DIR = HERE         # 图存这里；想换目录只改这一行
WAIT_MAX = 2400         # 最长等待秒数（Pro 档一般几分钟）


def ask(tip, default=""):
    try:
        s = input(tip + ((" [%s]" % default) if default else "") + " ：").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return s or default


def find_image(folder):
    """归档目录里的成品图（扩展名不定，逐个试）"""
    for fn in os.listdir(folder):
        if os.path.splitext(fn)[0].lower() == "image" and fn.lower().endswith(
                (".png", ".jpg", ".jpeg", ".webp")):
            return os.path.join(folder, fn)
    return ""


def main():
    print("=" * 62)
    print(" 模拟触发画图工具 flux_paint（生产链路 / Pro 档）")
    print("=" * 62)

    from func.toolbox.flux_painter.config import TBFluxPainterConfig
    from func.toolbox.flux_painter.comfy_connector.base import TBComfyBase
    from func.toolbox.flux_painter.painting_core import TBFluxPainterCore

    cfg = TBFluxPainterConfig()
    if not cfg.enabled:
        print("!! config.yml 里 flux_painter.enabled = false，绘画未启用，退出。")
        return 2

    core = TBFluxPainterCore()
    core.config.quality_mode = "pro"        # 本脚本固定走 Pro 档
    core.set_username("主人")

    # ---- 工具注册情况：证明走的确实是"工具被调用"这条路，而不是绕过去直接织图 ----
    tool_name = getattr(core, "TOOL_NAME", "flux_paint")
    try:
        tools = core.build_tools() or []
        names = [((t.get("function") or {}).get("name")) for t in tools
                 if isinstance(t, dict)]
        print("已注册工具 : %s" % [n for n in names if n])
    except Exception as e:
        print("已注册工具 : (读取失败 %s)" % e)
    print("本次调用   : dispatch(%r, {\"request\": ...})" % tool_name)
    print()
    print("底模      : %s" % core.config.unet_model)
    print("档位      : pro（模型放大 + 分块重绘 + 局部细化）")
    print("引擎      : %s %s:%s" % (cfg.comfy_mode, cfg.comfy_host, cfg.comfy_port))
    print("归档目录  : %s" % cfg.backup_dir)
    print("存图目录  : %s" % SAVE_DIR)
    print()

    # ---- 引擎没跑就先拉起来（内部内核，幂等） ----
    probe = TBComfyBase(cfg)
    if not probe.health():
        print("引擎未运行，正在启动（首次可能 1~3 分钟，请稍等）…")
        try:
            from func.toolbox.flux_painter.comfy_connector.comfy_painter import get_managed_painter
            ok, msg = get_managed_painter(cfg).start()
            print("  ->", ok, msg)
        except Exception as e:
            print("  启动失败：%s" % e)
        if not probe.health():
            print("!! 引擎仍不可用，先在「工具箱 → 绘画 → 服务」里启动，再重跑本脚本。")
            return 3
    print("引擎状态  : 已就绪")
    print()

    # 这里输入的是"需求原文"（跟你在 QQ 里对她说的一样），不是 tag 提示词
    request = ask("请输入绘画需求（像在 QQ 里说的那句话）")
    if not request:
        print("没输入，退出。")
        return 0

    before = set(os.listdir(cfg.backup_dir)) if os.path.isdir(cfg.backup_dir) else set()
    print("\n已触发，作画中（Pro 档通常几分钟）…\n")

    t0 = time.time()
    try:
        ret = core.dispatch(tool_name, {"request": request})
    except Exception:
        import traceback
        print("dispatch 异常：\n" + traceback.format_exc())
        return 4
    print("dispatch 返回 : %r" % (ret,))

    folder, image = "", ""
    while time.time() - t0 < WAIT_MAX:
        time.sleep(3)
        el = int(time.time() - t0)
        try:
            new = set(os.listdir(cfg.backup_dir)) - before
        except Exception:
            new = set()
        if new:
            d = sorted(new)[-1]
            p = find_image(os.path.join(cfg.backup_dir, d))
            if p and not core.is_painting():
                folder, image = os.path.join(cfg.backup_dir, d), p
                break
        if el % 15 < 3:
            print("  [%4ds] is_painting=%s" % (el, core.is_painting()))

    print()
    print("=" * 62)
    if not image:
        print("没有拿到成品图（超时 / 出图失败 / 被审查拦截）。")
        print("可看日志：logs/log_%s.txt 里搜 [flux_painter]" % datetime.date.today())
        return 5

    el = int(time.time() - t0)
    meta = {}
    mp = os.path.join(folder, "meta.json")
    if os.path.isfile(mp):
        try:
            with open(mp, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    ext = os.path.splitext(image)[1] or ".png"
    out_img = os.path.join(SAVE_DIR, "paint_%s%s" % (stamp, ext))
    out_txt = os.path.join(SAVE_DIR, "paint_%s.txt" % stamp)
    try:
        shutil.copy2(image, out_img)
    except Exception as e:
        print("复制到本目录失败：%s" % e)
        out_img = ""

    lines = [
        "时间        : %s" % datetime.datetime.now().isoformat(timespec="seconds"),
        "耗时        : %d 秒" % el,
        "工具        : %s" % tool_name,
        "需求原文    : %s" % request,
        "标题        : %s" % meta.get("title", ""),
        "档位        : %s" % meta.get("quality_mode", ""),
        "画布        : %s" % meta.get("canvas", ""),
        "底模        : %s" % core.config.unet_model,
        "归档        : %s" % folder,
        "本目录副本  : %s" % (out_img or "(复制失败)"),
        "",
        "LLM 产出的完整 positive:",
        str(meta.get("positive", "")),
        "",
        "完整 negative:",
        str(meta.get("negative", "")),
    ]
    try:
        with open(out_txt, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass

    print("完成，用时 %d 秒" % el)
    print("标题        : %s" % meta.get("title", ""))
    print("画布 / 档位 : %s / %s" % (meta.get("canvas", "?"), meta.get("quality_mode", "?")))
    print("生产归档    : %s" % folder)
    print("本目录成品图: %s" % (out_img or "(复制失败)"))
    print("本目录记录  : %s" % out_txt)
    print("=" * 62)

    try:
        os.startfile(out_img or image)      # 直接打开看
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\n已取消。")
