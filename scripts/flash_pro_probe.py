#!/usr/bin/env python
# -*- coding: utf-8 -*-
# scripts/flash_pro_probe.py
"""
flash 提示词 -> Anima pro 全流程 复现/诊断脚本（只调用现有生产代码，不修改任何生产文件）

目的
    1) 用「最新 flash 提示词 LLM」按生产同样的路径产出 positive/cinema（打印原始 tool-call 参数，
       重点看 character / character_known 字段是否被模型填了 true，从而跳过了角色查证）；
    2) 按生产同样的路径拼出 final_positive / negative（含画师、质量前缀），完整打印；
    3) 按生产同样的路径织 pro 图（build_pro_graph）并提交到内置引擎出图；
    4) 【核心】在链路每一级都挂一个 SaveImage，把 04基础 -> 05放大 -> 06分块 -> 07手/脸/眼
       逐级产物全部落盘，从而定位「脸是从哪一级开始跑偏的」；
    5) 可选 --mode both：同一 prompt + 同一 seed 同时跑「fast 单段」与「pro 全流程」，
       直接对比「基础出图的脸」与「pro 加工后的脸」——这是判断"模型不认识角色"还是
       "后处理毁脸"的决定性实验。

运行（必须用项目自带解释器；中文若乱码先执行 chcp 65001）
    chcp 65001
    runtime\\python.exe scripts\\flash_pro_probe.py --help
    runtime\\python.exe scripts\\flash_pro_probe.py                 # 默认即诗羽那张复现
    runtime\\python.exe scripts\\flash_pro_probe.py --mode both --dump-all
    runtime\\python.exe scripts\\flash_pro_probe.py --skip hires,usdu,eye      # 二分定位
    runtime\\python.exe scripts\\flash_pro_probe.py --no-artist --seed 12345   # 排除随机画师

    # 复用已有图：跳过 04 基础采样，直接从该图走 05 放大 -> 06 分块 -> 07 细化
    runtime\\python.exe scripts\\flash_pro_probe.py --from-image "character\\paints\\xxx\\image.png"
    runtime\\python.exe scripts\\flash_pro_probe.py --from-image latest            # 生产最新一张
    runtime\\python.exe scripts\\flash_pro_probe.py --from-image @base_sample     # 上次 dump 的基础图

注意
    * 全程只读生产代码，不改 config.yml、不改 workflow、不改任何 .py；
    * 本次 run 的 graph JSON、提示词、以及所有阶段图都会写到 --workdir 指定的目录（默认 logs/flux_probe）；
    * 出图可能 10 分钟以上（pro 档），请耐心等待。
"""
import argparse
import copy
import json
import os
import random
import re
import sys
import time
import datetime

# ---------------------------------------------------------------- 项目根引导
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)          # 生产代码大量使用相对路径（.ComfyNode / character / .temp），必须切到根目录

DEFAULT_REQUEST = "霞之丘诗羽，黑丝袜，微笑，害羞，较小的身体，场景在教室里，脚踩镜头，从人的45度前方拍"

DEFAULT_NEGATIVE = ("lowres,bad anatomy,bad hands,error,missing fingers,extra digits,"
                    "worst quality,jpeg artifacts,watermark,signature,text")


LOG_FILE = [None]           # 由 main 设置为 UTF-8 日志文件路径


def log(msg=""):
    line = str(msg)
    print(line, flush=True)
    p = LOG_FILE[0]
    if p:
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def hr(title=""):
    log("\n" + "=" * 78)
    if title:
        log(title)
        log("=" * 78)


# ---------------------------------------------------------------- 工具函数
def split_csv(text):
    return [x.strip().lower() for x in str(text or "").replace("，", ",").split(",") if x.strip()]


def canvas_to_wh(cfg, canvas):
    """与 painting_core._canvas_size 同逻辑：对齐 16 的倍数"""
    k = str(canvas or "").lower()
    for w, h in cfg.canvas_sizes:
        if k in (f"{w}x{h}", f"{w}*{h}"):
            return w - (w % 16), h - (h % 16)
    w, h = cfg.canvas_default
    return w - (w % 16), h - (h % 16)


def style_hint(text, keywords=None):
    """与 painting_core._style_hint 同逻辑（含"风格化"意图识别）
    返回 (style_extra, artist_kw, style_on)"""
    text = text or ""
    style_extra = [t.strip() for t in re.findall(r"@[\w\-_()（）]+", text)]
    artist_kw = ""
    m = re.search(r"(?:按|用|学|参考|模仿|来点|想要)([^，。！？\n]{1,10}(?:画师|老师|画风|风格))", text)
    if m:
        kw = re.sub(r"(画师|老师|画风|风格|的|风格|画|用|参考|模仿|来点|想要)", "", m.group(1)).strip(" ，。")
        if len(kw) >= 2:
            artist_kw = kw
    style_on = False
    if not artist_kw and not style_extra:
        low = text.lower()
        style_on = any(k.lower() in low for k in (keywords or []))
    return style_extra, artist_kw, style_on


def assemble_positive(cfg, picker, request, positive, cinema, use_random_artist=True,
                      extra_artists=None):
    """与 painting_core._run 中『画师串 + 质量前缀 + positive + cinema』同逻辑。
    画师规则（与生产一致）：默认不加画师；点名/@xxx/--artist 才用；只在要求"风格化"时从常驻名单随机抽 1。
    extra_artists: --artist 显式指定的画师（@ 可省略）"""
    debug = {}
    style_extra, artist_kw, style_on = style_hint(request, cfg.style_on_keywords)
    extra_artists = [str(x).strip() for x in (extra_artists or []) if str(x).strip()]
    if extra_artists:
        style_extra = extra_artists + style_extra      # 显式指定的放最前
        debug["artist_explicit"] = extra_artists
    debug["style_extra"] = style_extra
    debug["artist_kw_from_text"] = artist_kw
    debug["style_on"] = style_on
    # 只有"点名/显式/风格化"三者之一才会挂画师
    if (not artist_kw and not style_extra and not extra_artists and style_on
            and use_random_artist):
        _hits = picker.pick_artists(1)          # 与生产一致：从画师库 data.js 随机
        if _hits:
            artist_kw = str(_hits[0].get("name") or "").strip()
        debug["artist_random_picked"] = artist_kw or "(画师库为空)"
    else:
        debug["artist_random_picked"] = "(none)"

    named, manual = [], []
    if artist_kw:
        hit = None
        try:
            if picker.ensure_data()[0]:
                hit = picker.search(artist_kw, top=1)
        except Exception as e:
            debug["artist_search_error"] = str(e)
            hit = None
        if hit and hit[0].get("name") == artist_kw:
            named = [hit[0]]
        elif hit:
            manual.append("@" + str(hit[0].get("name") or "").strip())
        else:
            manual.append("@" + artist_kw)
    for s in style_extra:
        s = str(s).strip()
        tag = "@" + s.lstrip("@").strip()
        if s and tag not in manual:
            manual.append(tag)

    if artist_kw or manual:
        parts = ["@" + str(a.get("name") or "").strip() for a in named if a.get("name")]
        parts += manual
        artist_tags = ", ".join(parts) + ", " if parts else ""
    else:
        # 与生产一致：默认不加任何画师 tag
        artist_tags = ""
    quality = cfg.quality_prefix
    body = (positive.rstrip() + ", " + cinema) if cinema else positive
    final_positive = ((artist_tags + quality + ", " + body) if artist_tags
                      else ((quality + ", " + body) if quality else body))
    debug["artist_tags"] = artist_tags
    return final_positive, artist_tags, debug


def iter_image_stages(graph):
    """沿 SaveImage 反向遍历图像链，返回按时间顺序的 [(node_id, class_type), ...]"""
    src = None
    for nid, node in graph.items():
        if node.get("class_type") == "SaveImage":
            v = node.get("inputs", {}).get("images")
            if isinstance(v, list) and v and str(v[0]) in graph:
                src = str(v[0])
                break
    chain, seen = [], set()
    nid = src
    while nid and nid not in seen:
        seen.add(nid)
        node = graph.get(nid) or {}
        chain.append((nid, node.get("class_type", "?")))
        nxt = None
        for key in ("image", "upscaled_image", "samples"):
            v = (node.get("inputs") or {}).get(key)
            if isinstance(v, list) and len(v) == 2 and str(v[0]) in graph:
                nxt = str(v[0])
                break
        nid = nxt
    chain.reverse()
    return chain


IMAGE_STAGE_TYPES = ("VAEDecode", "ImageUpscaleWithModel", "ImageScale",
                     "UltimateSDUpscale", "UltimateSDUpscaleNoUpscale", "FaceDetailer")
DETAILER_ORDER = ("hand", "face", "eye")   # build_pro_graph 的链式顺序


def prune_unreachable(graph):
    """从 SaveImage 反向可达性裁剪：把 KSampler / EmptyLatentImage / VAEDecode 等
    不再被引用的节点删掉（ComfyUI 本来也不会执行，但删掉后 JSON 更直观）"""
    keep, stack = set(), [k for k, v in graph.items() if v.get("class_type") == "SaveImage"]
    while stack:
        nid = str(stack.pop())
        if nid in keep or nid not in graph:
            continue
        keep.add(nid)
        for v in (graph[nid].get("inputs") or {}).values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                stack.append(v[0])
    dropped = [k for k in graph if k not in keep]
    return {k: v for k, v in graph.items() if k in keep}, dropped


def apply_from_image(graph, image_path, base_node="8"):
    """把『04 基础采样』的输出（node 8 / VAEDecode）替换成读取已有图片：
    加 LoadImage(node 200) → 把所有引用 ["8",0] 的输入改指 ["200",0] → 裁掉不可达节点。
    结果：不再跑 KSampler，直接从已有图进入 05 放大 → 06 分块 → 07 细化。

    LoadImage 的 image 字段用 "<绝对路径> [output]" 注解式写法（注意空格），
    folder_paths.annotated_filepath 会剥掉注解、再 os.path.join(output_dir, 绝对路径)
    —— Windows 下 join 到绝对路径会直接取绝对路径，因此无需上传/拷贝文件。
    """
    g = copy.deepcopy(graph)
    g["200"] = {"class_type": "LoadImage", "inputs": {"image": f"{image_path} [output]"}}
    for _nid, node in g.items():
        for k, v in list((node.get("inputs") or {}).items()):
            if isinstance(v, list) and len(v) == 2 and str(v[0]) == base_node:
                node["inputs"][k] = ["200", v[1]]
    g, dropped = prune_unreachable(g)
    return g, dropped


def resolve_source_image(cfg, value):
    """把 --from-image 的值解析成绝对图片路径。
    支持：具体文件 / 目录(取最新图) / latest(生产最新) / @子串(模糊找最新一张)
    """
    import glob
    v = str(value or "").strip().strip('"').strip("'")
    if not v:
        return None
    if os.path.isfile(v):
        return os.path.abspath(v)

    def newest(patterns):
        files = []
        for p in patterns:
            files.extend(glob.glob(p, recursive=True))
        files = [f for f in files if os.path.isfile(f)]
        return max(files, key=os.path.getmtime) if files else None

    out_dir = cfg.comfy_output_dir
    if os.path.isdir(v):
        return newest([os.path.join(v, "**", "*.png"), os.path.join(v, "**", "*.jpg")])

    if v.lower() in ("latest", "last", "auto"):
        hit = newest([os.path.join(out_dir, "*.png"), os.path.join(out_dir, "*.jpg"),
                      os.path.join("character", "paints", "*", "image.png")])
        return os.path.abspath(hit) if hit else None

    if v.startswith("@"):
        sub = v[1:].strip().lower()
        files = []
        for p in (os.path.join(out_dir, "**", "*.png"),
                  os.path.join("logs", "flux_probe", "**", "*.png"),
                  os.path.join("character", "paints", "**", "*.png")):
            files.extend(glob.glob(p, recursive=True))
        files = [f for f in files if os.path.isfile(f) and sub in os.path.basename(f).lower()]
        return os.path.abspath(max(files, key=os.path.getmtime)) if files else None

    return None



def add_stage_dumps(graph, prefix):
    """在每一个 IMAGE 级节点后挂 SaveImage，返回 (新图, [(落盘名, 节点类, 节点id), ...])
    prefix 形如 "eriri_matrix/pro_dump/20260912_fast_A"，引擎支持 prefix 带 / 建子目录"""
    g = copy.deepcopy(graph)
    stages = [s for s in iter_image_stages(g)
              if s[1] in IMAGE_STAGE_TYPES]
    nice = {"VAEDecode": "base_sample", "ImageUpscaleWithModel": "hires_model4x",
            "ImageScale": "hires_scaled", "UltimateSDUpscaleNoUpscale": "usdu_tiled",
            "UltimateSDUpscale": "usdu", "FaceDetailer": "detailer"}
    plan, det_idx = [], 0
    for i, (nid, ct) in enumerate(stages, 1):
        name = nice.get(ct, ct)
        if ct == "FaceDetailer":
            who = DETAILER_ORDER[det_idx] if det_idx < len(DETAILER_ORDER) else f"n{det_idx + 1}"
            det_idx += 1
            name = f"{name}_{det_idx}_{who}"
        name = f"{i:02d}_{name}"
        plan.append((name, ct, nid))
        g[f"9{i:03d}"] = {"class_type": "SaveImage",
                          "inputs": {"images": [nid, 0],
                                     "filename_prefix": f"{prefix}/{name}"}}
    return g, plan


def resolve_platform(cfg):
    """与 painting_core._ensure_comfy 同逻辑：内置引擎启动 / 外部引擎探测"""
    from func.toolbox.flux_painter.comfy_connector import create_connector
    if cfg.comfy_mode == "external":
        conn = create_connector(cfg)
        ok, msg = conn.ensure_ready()
        return conn, ok, msg
    from func.toolbox.flux_painter.comfy_connector.comfy_painter import get_managed_painter
    ok, msg = get_managed_painter(cfg).start()
    return create_connector(cfg), ok, msg


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="flash->pro 画图链路复现与诊断（只读，不改生产代码）")
    ap.add_argument("--request", default=DEFAULT_REQUEST, help="绘画需求文本")
    ap.add_argument("--positive", default=None,
                    help="直接用给定 positive（跳过 LLM，纯测引擎链路；与 --request 二选一）")
    ap.add_argument("--cinema", default=None, help="配合 --positive 使用的自然语言段（可空）")
    ap.add_argument("--mode", default="pro", choices=["pro", "fast", "both"],
                    help="跑哪个档位：pro 全流程 / fast 单段 / both 同 seed 对比（默认 pro）")
    ap.add_argument("--from-image", default=None,
                    help="复用已有图片，跳过 04 基础采样，直接从该图进入 05 放大->06 分块->07 细化。"
                         "取值：文件路径 / 目录(取最新) / latest(生产最新一张) / @子串(如 @base_sample)")
    ap.add_argument("--canvas", default=None, help="画布，如 1080x1440；默认用配置默认画布")
    ap.add_argument("--seed", type=int, default=None, help="固定随机种子（默认随机，但会打印出来）")
    ap.add_argument("--model", default=None, help="覆盖提示词 LLM 模型名，如 deepseek-flash")
    ap.add_argument("--skip", default="", help="禁用 pro 的若干环节：hires,usdu,hand,face,eye（可逗号分隔）")
    ap.add_argument("--lora-mul", type=float, default=None,
                    help="把所有 LoRA 强度整体乘以该系数（0=等于关掉 LoRA），用于判定美学 LoRA 是否洗掉角色特征")
    ap.add_argument("--no-lora", action="store_true", help="等价于 --lora-mul 0（彻底不加载 LoRA 权重）")
    ap.add_argument("--no-artist", action="store_true", help="不注入常驻随机画师（用于排除画师干扰）")
    ap.add_argument("--label", default="", help="本次运行的短标签，写进出图文件名（如 A_sawamura_eriri），便于批量对比")
    ap.add_argument("--artist", default="",
                    help="显式指定画师 tag（@ 可省略，多个用逗号分隔），"
                         "与生产同格式 @name 置于提示词最前；指定后不再随机抽常驻画师")
    ap.add_argument("--out-subdir", default="",
                    help="把出图收进 output 下的子目录（如 eriri_matrix），便于整批对比")
    ap.add_argument("--negative", default=None, help="覆盖负面提示词（默认用 config.yml 的 negative_prompt）")
    ap.add_argument("--no-persona", action="store_true", help="不注入角色人设/记忆（纯需求）")
    ap.add_argument("--no-dump-all", dest="dump_all", action="store_false",
                    help="关闭逐级落盘（默认开启：04基础/05放大/06分块/07手/脸/眼 全留档）")
    ap.set_defaults(dump_all=True)
    ap.add_argument("--dry", action="store_true", help="只出提示词与 graph JSON，不提交引擎")
    ap.add_argument("--ignore-missing", action="store_true", help="pro 节点缺失时也强行提交")
    ap.add_argument("--timeout", type=int, default=2400, help="等待出图超时秒数")
    ap.add_argument("--workdir", default=os.path.join("logs", "flux_probe"), help="本次实验产物目录")
    ap.add_argument("--open", action="store_true", help="结束后打开产物目录")
    args = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = os.path.abspath(os.path.join(args.workdir, stamp))
    os.makedirs(workdir, exist_ok=True)
    LOG_FILE[0] = os.path.join(workdir, "00_run.log")     # 全程日志 UTF-8 落盘

    from func.toolbox.flux_painter.config import TBFluxPainterConfig
    from func.toolbox.flux_painter.prompt_producer import TBPromptProducer
    from func.toolbox.flux_painter.comfy_connector import create_connector, TBArtistPicker
    from func.toolbox.flux_painter.comfy_connector.artist import (
        ARTIST_RANDOM_MIN_POSTS, ARTIST_RANDOM_MAX_POOL)

    cfg = TBFluxPainterConfig()
    if args.model:
        if cfg.llm_type == "aliyun":
            cfg.aliyun_model = args.model
        else:
            cfg.deepseek_model = args.model

    hr("0. 环境")
    log(f"项目根目录      : {ROOT}")
    log(f"解释器          : {sys.executable}")
    log(f"实验产物目录    : {workdir}")
    log(f"绘画模块 enabled: {cfg.enabled}")
    log(f"引擎模式        : {cfg.comfy_mode}  {cfg.comfy_host}:{cfg.comfy_port}")
    log(f"画质档位(配置)  : {cfg.quality_mode}   -> 本次 --mode={args.mode}")
    act = cfg.active_llm()
    log(f"提示词 LLM      : provider={act['llm_type']}  model={act['model']}  "
        f"thinking={cfg.thinking_enabled}  temperature={cfg.temperature}")
    log(f"LoRA 链         : {[ (l['name'], l['strength']) for l in cfg.lora_chain ]}")
    log(f"风格化画师库    : {cfg.artist_data}"
        f"（随机池: post_count>={ARTIST_RANDOM_MIN_POSTS} 且前 {ARTIST_RANDOM_MAX_POOL} 名）")
    log(f"质量前缀        : {cfg.quality_prefix!r}")
    log(f"负面提示词      : {(cfg.negative_prompt or '(空->用内置)')!r}")
    log(f"sampler         : {cfg.sampler_name}/{cfg.sampler_scheduler} "
        f"steps={cfg.sampler_steps} cfg={cfg.sampler_cfg} shift={cfg.sampler_shift}")

    # ------------------------------------------------ 1. 提示词（走最新 flash）
    hr("1. 提示词生成（生产同路径：TBPromptProducer，法典自主检索 + function calling）")
    t0 = time.time()
    if args.positive:
        # 跳过 LLM：直接用给定 prompt 测引擎链路
        positive = str(args.positive).strip()
        cinema = str(args.cinema or "").strip()
        character, ck = "", None
        log("（--positive 指定：跳过 LLM 调用，直接使用给定提示词）")
        el = 0.0
    else:
        persona = ""
        memories = []
        if not args.no_persona:
            try:
                from func.pipeline.short_memory import ShortMemory
                memories = ShortMemory().load()[-6:]
            except Exception as e:
                log(f"（短期记忆读取失败，忽略：{e}）")
        producer = TBPromptProducer(cfg)
        elements = producer.run(args.request, username="主人", persona=persona, memory=memories)
        el = time.time() - t0
        if not elements:
            log("!! 提示词生成失败（producer 返回 None），无法继续。请检查 API key / 网络 / 日志。")
            return 2
        positive = str(elements.get("positive") or "").strip()
        cinema = str(elements.get("cinema") or "").strip()
        character = str(elements.get("character") or "").strip()
        ck = elements.get("character_known")
    log(f"耗时 {el:.1f}s")
    if args.positive:
        log(f"title            : (--positive 模式无)")
        log(f"canvas(raw)      : (未指定，用配置默认)")
    else:
        log(f"title            : {elements.get('title')}")
        log(f"canvas(raw)      : {elements.get('canvas')}")
        cv = elements.get("canvas")
    log(f"character        : {character!r}")
    log(f"character_known  : {ck!r}   <- 若为 True/None，生产链路会『跳过』本地词典+萌娘查证")
    log(f"positive(锚点段) : {positive}")
    log(f"cinema(自然语言) : {cinema}")
    if not args.positive:
        with open(os.path.join(workdir, "01_llm_elements.json"), "w", encoding="utf-8") as f:
            json.dump(dict(elements), f, ensure_ascii=False, indent=2)

    # ------------------------------------------------ 2. 拼最终提示词（含画师/质量前缀）
    hr("2. 最终提示词拼装（生产同逻辑：常驻随机画师 + 质量前缀 + positive + cinema）")
    picker = TBArtistPicker(cfg)
    extra_artists = [x for x in re.split(r"[,\s]+", str(args.artist or "").strip()) if x]
    final_positive, artist_tags, dbg = assemble_positive(
        cfg, picker, args.request, positive, cinema,
        use_random_artist=not args.no_artist, extra_artists=extra_artists)
    negative = args.negative if args.negative else (cfg.negative_prompt or DEFAULT_NEGATIVE)
    log(f"随机画师抽中    : {dbg.get('artist_random_picked')}")
    log(f"显式画师(--artist): {dbg.get('artist_explicit') or '(无)'}")
    log(f"实际画师串      : {artist_tags!r}")
    log("")
    log("FINAL POSITIVE :")
    log(final_positive)
    log("")
    log("NEGATIVE       :")
    log(negative)
    with open(os.path.join(workdir, "02_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(f"REQUEST:\n{args.request}\n\nARTIST_TAGS:\n{artist_tags}\n\n"
                f"POSITIVE:\n{final_positive}\n\nNEGATIVE:\n{negative}\n")
    # 便利检查：positive 的头部 tag（含角色 tag）是否被原样保留进最终提示词
    probe_tags = [t.strip() for t in str(positive).split(",") if t.strip()][:6]
    if not probe_tags:
        probe_tags = ["kasumigaoka utaha", "saenai", "hairband", "pantyhose", "purple eyes"]
    log("")
    log("positive 头部 tag 是否原样保留在 final_positive（大小写不敏感）:")
    low = final_positive.lower()
    for t in probe_tags:
        log(f"   {'[OK]' if t in low else '[--]'}  {t}")

    # ------------------------------------------------ 3. 画布 / seed
    canvas = (args.canvas
              or (None if args.positive else (cv or None))
              or f"{cfg.canvas_default[0]}x{cfg.canvas_default[1]}")
    w, h = canvas_to_wh(cfg, canvas)
    seed = args.seed if args.seed is not None else random.randint(0, 2 ** 63 - 1)
    hr("3. 采样参数")
    log(f"canvas={canvas}  -> ComfyUI 实际 {w}x{h}   seed={seed}")

    # ---- 是否复用已有图（跳过 04 基础采样，直接进 05 放大 + 06 分块 + 07 细化）----
    from_image = None
    if args.from_image:
        from_image = resolve_source_image(cfg, args.from_image)
        if not from_image or not os.path.isfile(from_image):
            log(f"!! 找不到源图：--from-image {args.from_image!r}")
            return 5
        try:
            mt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(from_image)))
        except Exception:
            mt = "?"
        log(f"源图            : {from_image}")
        log(f"源图时间        : {mt}")
        log("模式            : 跳过 04 基础采样(KSampler/EmptyLatentImage) -> 05 放大 -> 06 分块 -> 07 细化")
        log("提示            : 想要与『原图那次』公平对比，请把 --seed 设成当初那张图打印出来的 seed")
        if args.mode == "fast":
            log("!! --from-image 与 --mode fast 冲突（fast 档就是基础采样本身）。已自动切到 pro。")
            args.mode = "pro"
    modes = ["fast", "pro"] if args.mode == "both" else [args.mode]
    if from_image:
        modes = [m for m in modes if m == "pro"]
    log(f"本次实际出图档位: {modes}")

    if args.dry:
        log("\n--dry 指定：跳过引擎与提交。")
        # 还是把 graph 落盘，便于肉眼核对
        conn = create_connector(cfg)
        for m in modes:
            g = _build_graph(cfg, conn, m, final_positive, negative, w, h, seed, args,
                             from_image=from_image)
            if args.dump_all:
                _t = f"{stamp}_{m}{('_' + _label(args)) if _label(args) else ''}"
                g, plan = add_stage_dumps(g, f"{_out_root(args)}pro_dump/{_t}")
                log(f"（--dump-all）{m} 档将逐级落盘：")
                for name, ct, nid in plan:
                    log(f"   {name:26s} <- node {nid} ({ct})")
            p = os.path.join(workdir, f"03_graph_{m}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(g, f, ensure_ascii=False, indent=1)
            log(f"graph[{m}] -> {p} （{len(g)} 个节点）")
        return 0

    # ------------------------------------------------ 4. 引擎
    hr("4. 绘图引擎")
    conn, ok, msg = resolve_platform(cfg)
    log(f"启动/复用：ok={ok}  {msg}")
    if not ok:
        log("!! 引擎未就绪，终止。")
        return 3
    log(f"health={conn.health()}")

    # pro 节点自检
    if args.mode in ("pro", "both"):
        try:
            missing = conn.missing_pro_nodes()
        except Exception as e:
            missing = f"(检查异常 {e})"
        log(f"pro 必需节点缺失: {missing if not isinstance(missing, list) else (missing or '无')}")
        if isinstance(missing, list) and missing and not args.ignore_missing:
            log("!! pro 档位节点缺失。加 --ignore-missing 可强行提交；否则请检查自定义节点。")
            return 4

    # ------------------------------------------------ 5. 提交
    results = {}
    for m in modes:
        hr(f"5. 出图 —— {m} 档（seed 复用 {seed}）"
           + ("  [跳过04基础采样，直接后处理]" if from_image else ""))
        graph = _build_graph(cfg, conn, m, final_positive, negative, w, h, seed, args,
                             from_image=from_image)
        plan = []
        if args.dump_all:
            tag = f"{stamp}_{m}{('_' + _label(args)) if _label(args) else ''}"
            graph, plan = add_stage_dumps(graph, f"{_out_root(args)}pro_dump/{tag}")
            log("已挂载逐级落盘节点：")
            for name, ct, nid in plan:
                log(f"   {name:22s} <- node {nid} ({ct})")
        gp = os.path.join(workdir, f"04_graph_{m}.json")
        with open(gp, "w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False, indent=1)
        log(f"graph JSON -> {gp}（{len(graph)} 节点）")

        prefix = f"probe_{stamp}_{m}"
        # 与生产一致：pro 提交失败自动降级 fast 重试（--from-image 时无法降级，直接报错）
        sok, prompt_id, serr = conn.submit(graph, client_id=f"probe_{m}")
        if not sok and m == "pro" and not from_image:
            log(f"!! pro 图提交失败：{serr}\n   -> 自动降级为 fast 单段重试（与生产同行为）")
            graph = _build_graph(cfg, conn, "fast", final_positive, negative, w, h, seed, args)
            sok, prompt_id, serr = conn.submit(graph, client_id="probe_fast_fb")
        if not sok:
            log(f"!! 提交失败：{serr}")
            results[m] = ("提交失败", serr)
            continue
        log(f"已提交 prompt_id={prompt_id}，等待出图…（超时 {args.timeout}s）")
        t1 = time.time()
        last = {"t": 0.0}

        def on_progress(ev):
            now = time.time()
            if now - last["t"] < 3 and ev.get("percent", 0) < 100:
                return
            last["t"] = now
            log(f"   [{int(now - t1):5d}s] {ev.get('percent', 0):3d}%  {ev.get('stage', '')} "
                f"{ev.get('step', '')}")

        wok, images, wmsg = conn.watch(prompt_id, graph=graph, timeout=args.timeout,
                                       client_id=f"probe_{m}", on_progress=on_progress)
        dt = int(time.time() - t1)
        if not wok:
            log(f"!! 出图失败（{dt}s）：{wmsg}")
            results[m] = ("失败", wmsg)
            continue
        paths = conn.images_local(images) or []
        log(f"出图完成（{dt}s），产出 {len(paths)} 张：")
        staged = {}
        for p in sorted(paths):
            log(f"   {p}")
            base = os.path.basename(p)
            staged[base] = p
        results[m] = ("成功", paths)

    # ------------------------------------------------ 6. 汇总
    hr("6. 汇总：逐级产物对照（重点看 脸 从哪一级开始变）")
    for m, (st, info) in results.items():
        if st == "成功":
            log(f"\n[{m}] 成功，{len(info)} 张")
            for p in sorted(info):
                name = os.path.basename(p)
                log(f"   {name}")
        else:
            log(f"\n[{m}] {st}: {info}")
    log("")
    log(f"实验目录：{workdir}")
    log("建议查看顺序（若开了 --dump-all）：")
    log("   base_sample -> hires_model4x -> hires_scaled -> usdu_tiled -> detailer…（手/脸/眼，按序）")
    log("   若 base_sample 的脸就已经不是角色本人 -> 问题在『模型/提示词/角色tag』，不在后处理；")
    log("   若 base_sample 对、detailer 之后跑偏 -> 问题在 pro 的 05/06/07 后处理（放大+分块+重绘）。")

    if args.open:
        try:
            os.startfile(workdir)      # noqa
        except Exception:
            pass
    return 0


def _label(args):
    """--label 清洗为文件名安全片段（用于区分同一批次的多次运行，避免输出互相覆盖）"""
    lab = re.sub(r"[^0-9A-Za-z_\-]+", "_", str(getattr(args, "label", "") or "")).strip("_")
    return lab


def _out_root(args):
    """--out-subdir：把本批结果收进 output 下的子目录（引擎支持 prefix 里带 /）"""
    sub = str(getattr(args, "out_subdir", "") or "").strip().strip("/\\")
    sub = re.sub(r"[^0-9A-Za-z_\-/\\]+", "_", sub).replace("\\", "/").strip("/")
    return (sub + "/") if sub else ""


def _build_graph(cfg, conn, mode, final_positive, negative, w, h, seed, args,
                 from_image=None):
    """按档位织图；--skip 可禁用 pro 的若干环节用于二分定位；
    from_image 非空时：跳过 04 基础采样，直接从该图进入 05 放大 -> 06 分块 -> 07 细化"""
    lab = _label(args)
    suffix = ("_" + lab) if lab else ""
    root = _out_root(args)
    if mode == "fast":
        if from_image:
            raise RuntimeError("--from-image 只能配合 --mode pro/both 的 pro 部分使用"
                               "（fast 档本身就是基础采样，没有可跳过的后处理）")
        g = conn.build_graph(final_positive, negative, w, h,
                             prefix=f"{root}probe_fast{suffix}",
                             clip_type="qwen_image", seed=seed)
        _scale_lora(g, args)
        return g
    pro_p = copy.deepcopy(cfg.pro)
    skip = set(split_csv(args.skip))
    if "hires" in skip:
        pro_p.setdefault("hires", {})["enabled"] = False
    if "usdu" in skip:
        pro_p.setdefault("usdu", {})["enabled"] = False
    for k in ("hand", "face", "eye"):
        if k in skip:
            pro_p.setdefault("detailers", {}).setdefault(k, {})["enabled"] = False
    g = conn.build_pro_graph(final_positive, negative, w, h,
                             prefix=f"{root}probe_pro{suffix}",
                             clip_type="qwen_image", seed=seed, params=pro_p)
    _scale_lora(g, args)
    if from_image:
        g, dropped = apply_from_image(g, from_image)
        log(f"[from-image] 已跳过 04 基础采样；裁掉不可达节点: {sorted(dropped)}")
        log(f"[from-image] 起点图 = {from_image}")
    return g


def _scale_lora(graph, args):
    """按 --lora-mul / --no-lora 调整图里所有 LoraLoaderModelOnly 的 strength_model，
    用来判定『美学/细节 LoRA 是不是把可爱脸洗成御姐脸』"""
    mul = 1.0
    if getattr(args, "no_lora", False):
        mul = 0.0
    elif getattr(args, "lora_mul", None) is not None:
        mul = float(args.lora_mul)
    if abs(mul - 1.0) < 1e-9:
        return
    hits = []
    for nid, node in graph.items():
        if node.get("class_type") == "LoraLoaderModelOnly":
            old = float(node["inputs"].get("strength_model", 0.0))
            node["inputs"]["strength_model"] = round(old * mul, 4)
            hits.append(f"{node['inputs'].get('lora_name')}: {old} -> {node['inputs']['strength_model']}")
    log(f"[lora] 强度 x{mul}：" + ("; ".join(hits) if hits else "（图中无 LoRA 节点）"))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断")
        sys.exit(130)
