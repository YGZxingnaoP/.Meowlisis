# -*- coding: utf-8 -*-
# scripts/real_paint_test.py
"""真画测试：走**生产真实链路**跑一张完整画作，并把关键信息打成报告。

与 flash_pro_probe.py 的区别：
    flash_pro_probe  = 探针，自己拼提示词/图，可控性强但绕开了生产逻辑
    real_paint_test  = 真画，直接调 TBFluxPainterCore.dispatch（= 主程序/QQ 走的那条路）
                       → 真 LLM 产词（含法典+function calling）→ 真 pro/fast 渲染
                       → 真归档 character/paints/<时间>_<标题>/ → 真审查 → 真写记忆

报告会核对三件事（都是最近改过的规则）：
    ① 画师串：应为空（默认不加画师）；只有点名或"风格化"才非空
    ② cinema 是否写了光照（用生产的 LIGHT_RE 判定）
    ③ 出图亮度（平均/暗部占比），用于对比"普遍偏暗"

跑法（项目根目录）：
    runtime\\python.exe scripts\\real_paint_test.py --request "英梨梨，白丝袜，教室，脚踩镜头"
    runtime\\python.exe scripts\\real_paint_test.py --request "画个诗羽，教室，风格化一点"     # 验证风格化分支
    runtime\\python.exe scripts\\real_paint_test.py --request "..." --timeout 2400 --no-open

产物（**不写 .temp**）：
    logs/paint_test/<时间戳>.txt   报告
    character/paints/<时间>_<标题>/  画作 + meta.json（生产正常归档）
"""
import argparse
import datetime
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)          # 生产代码大量用相对路径，必须切到根目录

LOG_LINES = []


def log(msg=""):
    line = str(msg)
    LOG_LINES.append(line)
    try:
        print(line, flush=True)
    except Exception:
        print(line.encode("utf-8", "replace").decode("gbk", "replace"), flush=True)


def hr(title=""):
    log("")
    log("=" * 78)
    if title:
        log(title)
        log("=" * 78)


def snap_dirs(path):
    try:
        return {d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))}
    except Exception:
        return set()


def log_file_path():
    return os.path.join("logs", f"log_{datetime.datetime.now():%Y-%m-%d}.txt")


def read_new_log(path, start_size):
    """读日志文件新增部分（用于抓本次运行的 [flux_painter] 行）"""
    try:
        if not os.path.isfile(path):
            return []
        if os.path.getsize(path) <= start_size:
            return []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(start_size)
            return [ln.rstrip() for ln in f if "[flux_painter]" in ln]
    except Exception:
        return []


def brightness(path):
    try:
        from PIL import Image
        import numpy as np
        with Image.open(path) as im:
            g = im.convert("L")
            if max(g.size) > 256:
                g = g.resize((256, 256), Image.BILINEAR)
            a = np.asarray(g, dtype=np.float32) / 255.0
        return a.mean() * 100.0, float((a < 0.20).mean() * 100.0), float((a > 0.90).mean() * 100.0)
    except Exception as e:
        return None, None, str(e)


def split_positive(positive):
    """启发式把 positive 切成 (画师串, tag段, cinema)"""
    pos = str(positive or "")
    m = re.match(r"^((?:@[^,]+,\s*)+)", pos)
    artists = m.group(1).strip().rstrip(",") if m else ""
    rest = pos[len(m.group(1)):] if m else pos
    toks = rest.split(", ")
    cut = None
    for i, t in enumerate(toks):
        if re.match(r"^[A-Z][a-z]+ ", t.strip()):
            cut = i
            break
    if cut is None:
        return artists, rest, ""
    return artists, ", ".join(toks[:cut]), ", ".join(toks[cut:])


def ensure_board(cfg, url, timeout=10):
    """确保画板服务在线（HTTP 8090 托管页面 + WS 8767 推送），返回 (在线?, 说明)

    - 主程序（api.py）已起过画板 -> 直接复用，不重复启动
    - 没起过 -> 本次测试自己 start()（幂等）
    - 画板默认频道是 live，而 dispatch 用的就是 live，所以推送能直接落到页面上
    """
    import urllib.request

    def alive():
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return int(getattr(r, "status", 200)) == 200
        except Exception:
            return False

    if alive():
        return True, "画板服务已在运行（复用主程序起的那个）"
    try:
        from func.toolbox.flux_painter.server import get_flux_painter_server
        get_flux_painter_server().start()
    except Exception as e:
        return False, "画板服务启动异常: " + str(e)
    for _ in range(max(1, timeout)):
        if alive():
            return True, "画板服务已由本次测试启动"
        time.sleep(1)
    return False, "画板服务未在 " + str(timeout) + "s 内就绪（端口可能被占用）"


def main():
    ap = argparse.ArgumentParser(description="真画测试（走生产链路）")
    ap.add_argument("--request", required=True, help="绘画需求原文（中文，和你在 QQ 里说的一样）")
    ap.add_argument("--username", default="主人", help="署名（写入 meta/记忆）")
    ap.add_argument("--timeout", type=int, default=1800, help="最长等待秒数")
    ap.add_argument("--poll", type=int, default=5, help="轮询间隔秒")
    ap.add_argument("--report-dir", default=os.path.join("logs", "paint_test"))
    ap.add_argument("--no-open", action="store_true", help="不自动打开出图")
    ap.add_argument("--no-board", action="store_true", help="不启动/不打开画板页面")
    ap.add_argument("--board-url", default="", help="画板地址（默认按 config 的 http_port 拼）")
    args = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    os.makedirs(args.report_dir, exist_ok=True)
    report_path = os.path.join(args.report_dir, f"{stamp}.txt")
    lg = log_file_path()
    lg_size0 = os.path.getsize(lg) if os.path.isfile(lg) else 0

    from func.toolbox.flux_painter.config import TBFluxPainterConfig
    from func.toolbox.flux_painter.painting_core import TBFluxPainterCore
    try:
        from func.toolbox.flux_painter.prompt_producer import LIGHT_RE
    except Exception:
        LIGHT_RE = None

    cfg = TBFluxPainterConfig()
    hr("0. 环境")
    log(f"需求          : {args.request!r}")
    log(f"绘画开关      : {cfg.enabled}")
    log(f"画质档位      : {cfg.quality_mode}")
    log(f"风格化画师库  : {cfg.artist_data}")
    log(f"风格化触发词  : {cfg.style_on_keywords}")
    log(f"质量前缀      : {cfg.quality_prefix}")
    log(f"负面提示词    : {cfg.negative_prompt[:120]}")
    log(f"LoRA 链       : {[(x.get('name'), x.get('strength'), x.get('enabled')) for x in (cfg.lora_chain or [])]}")
    log(f"引擎          : {cfg.comfy_mode} {cfg.comfy_host}:{cfg.comfy_port}")
    log(f"审查          : enabled={cfg.review_enabled} mode={cfg.review_mode}")
    log(f"归档目录      : {cfg.backup_dir}")
    log(f"本次报告      : {report_path}（产物全部落 logs/，不碰 .temp）")
    if not cfg.enabled:
        log("\n!! 绘画模块未启用（config.yml → flux_painter.enabled=false），无法真画。终止。")
        return 2

    # ---- 画板：确保服务在线并打开，出图全程可在页面上看到实时推送 ----
    board_url = args.board_url or "http://127.0.0.1:" + str(cfg.http_port) + "/painting_board.html"
    if args.no_board:
        log("画板          : 已跳过（--no-board）")
    else:
        ok, why = ensure_board(cfg, board_url)
        log("画板          : " + board_url)
        log("                " + why)
        log("                推送频道 = live（dispatch 用的就是 live，画板默认频道也是 live）")
        if ok:
            try:
                import webbrowser
                webbrowser.open(board_url)
                log("                已打开画板：出图过程中能看到 status/producing/prompt/progress/done 实时推送")
            except Exception as e:
                log("                浏览器打开失败(" + str(e) + ")，请手动访问上面的地址")
        log("                注：画板服务随本脚本进程存活，脚本退出后页面就不再更新")

    before = snap_dirs(cfg.backup_dir)
    hr("1. 起画（production dispatch）")
    core = TBFluxPainterCore()
    core.set_username(args.username)
    t0 = time.time()
    try:
        ret = core.dispatch(core.TOOL_NAME, {"request": args.request})
    except Exception:
        import traceback
        log("dispatch 异常：\n" + traceback.format_exc())
        return 4
    log(f"dispatch 返回 : {ret}")

    hr("2. 等待完成（真 LLM 产词 + 真渲染 + 真归档）")
    new_dir, img_path = "", ""
    timed_out = False
    while True:
        time.sleep(max(1, args.poll))
        el = int(time.time() - t0)
        cur = snap_dirs(cfg.backup_dir) - before
        if cur:
            d = sorted(cur)[-1]
            img = os.path.join(cfg.backup_dir, d, "image.png")
            if os.path.isfile(img) and not core.is_painting():
                new_dir, img_path = d, img
                log(f"   [{el:5d}s] 归档完成: {d}")
                break
        if el > args.timeout:
            timed_out = True
            log(f"   [{el:5d}s] 超时（{args.timeout}s），停止等待")
            break
        if el % 30 < args.poll:
            log(f"   [{el:5d}s] 绘画中… (is_painting={core.is_painting()})")

    # ------------------------------------------------ 3. 结果核对
    hr(f"3. 结果（耗时 {int(time.time() - t0)}s{'，已超时' if timed_out else ''}）")
    meta = {}
    if new_dir:
        mp = os.path.join(cfg.backup_dir, new_dir, "meta.json")
        if os.path.isfile(mp):
            try:
                import json
                with open(mp, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception as e:
                log(f"meta.json 读取失败: {e}")
    if not meta:
        if timed_out:
            log("超时未拿到归档结果。检查 logs 里的报错；也可加大 --timeout 后重跑。")
        else:
            log("没有新归档（可能出图失败/被审查拦截）。看下面的 [flux_painter] 日志。")
    else:
        positive = str(meta.get("positive") or "")
        artists, tags, cinema = split_positive(positive)
        canvas = meta.get("canvas", "?")
        log(f"标题          : {meta.get('title')}")
        log(f"画布          : {canvas}")
        log(f"档位          : {meta.get('quality_mode')}")
        log(f"归档          : {os.path.join(cfg.backup_dir, new_dir)}")
        log("")
        log(f"① 画师串      : {artists or '(空)'}")
        if artists:
            log("   → 有画师：说明命中了『点名』或『风格化随机』分支")
        else:
            log("   → 无画师：命中默认分支 ✓（画师默认不加）")
        log("")
        log(f"tag 锚点段    : {tags}")
        log("")
        log(f"cinema 主描述 : {cinema or '(切分失败，见下方完整提示词)'}")
        if LIGHT_RE is not None and cinema:
            hits = sorted({m.group(0).lower() for m in LIGHT_RE.finditer(cinema)})
            log(f"② 光照判定    : {'OK 写了光照' if hits else '!! 未见光照词'}  {hits[:10]}")
        log("")
        log("完整 positive :")
        log(f"   {positive}")
        log("")
        log("完整 negative :")
        log(f"   {meta.get('negative')}")
        if img_path:
            mean, dark, err = brightness(img_path)
            if mean is None:
                log(f"③ 亮度        : 统计失败 {err}")
            else:
                log(f"③ 亮度        : 平均 {mean:.1f}   暗部<20% {dark:.1f}%   高光>90% {brightness(img_path)[2]:.1f}%")
                log("   （历史基线：旧格式 60~80；改前那两三张 34~41）")

    hr("4. 本次运行的生产日志（[flux_painter] 行）")
    for ln in read_new_log(lg, lg_size0):
        log("   " + ln)

    hr("5. 结论速览")
    if meta:
        artists, _, cinema = split_positive(meta.get("positive"))
        light_ok = bool(LIGHT_RE.search(cinema)) if (LIGHT_RE and cinema) else None
        log(f"   画师默认不加: {'✓' if not artists else '✗ ' + artists}")
        log(f"   cinema 有光照: {'✓' if light_ok else ('✗' if light_ok is False else '?')}")
        if img_path:
            mean, dark, _ = brightness(img_path)
            if mean is not None:
                log(f"   平均亮度      : {mean:.1f}（{'偏暗' if mean < 45 else '正常' if mean < 60 else '偏亮'}）")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))
    log("")
    log(f"报告已写入: {report_path}")
    if img_path and not args.no_open:
        try:
            os.startfile(img_path)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
