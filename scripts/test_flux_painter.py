# -*- coding: utf-8 -*-
# scripts/test_flux_painter.py
# Flux 绘画测试：模式一 --selftest（离线自检）；模式二 无参运行 = 端到端真画
#   真画默认请求：画一个黑长直美女在自慰（可传参覆盖，如：
#   runtime\python.exe scripts\test_flux_painter.py 画一个在教室里的女仆
# 端到端 = 父级工具 flux_paint 触发 → 提示词LLM → 内置ComfyUI出图 → 归档 character/paints
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def selftest():
    ok_all = True

    def check(name, cond, extra=""):
        nonlocal ok_all
        mark = "PASS" if cond else "FAIL"
        if not cond:
            ok_all = False
        print(f"  [{mark}] {name} {extra}")

    from func.toolbox.flux_painter.config import TBFluxPainterConfig
    from func.toolbox.flux_painter.knowledge import TBAnimaKnowledge
    from func.toolbox.flux_painter.painting_core import TBFluxPainterCore
    from func.toolbox.flux_painter.comfy_connector.base import TBComfyBase
    from func.toolbox.flux_painter.comfy_connector.artist import TBArtistPicker
    from func.toolbox.flux_painter.archive import TBPainterArchive
    import tempfile

    cfg = TBFluxPainterConfig()
    print("[1] 配置")
    check("enabled", cfg.enabled)
    check("画布两档", cfg.canvas_sizes == [(1024, 1024), (1080, 1960)], str(cfg.canvas_sizes))
    check("LLM=deepseek", cfg.active_llm().get("llm_type") == "deepseek")
    check("comfy internal", cfg.comfy_mode == "internal")
    check("工具名", TBFluxPainterCore.TOOL_NAME == "flux_paint")

    print("[2] 提示词法典检索")
    k = TBAnimaKnowledge(cfg)
    ok, md = k.ensure_md()
    check("法典就绪", ok and os.path.isfile(md))
    head, sec = k.retrieve("兽耳娘在雨中瑟瑟发抖")
    check("命中兽耳章节", "兽耳/尾" in sec, sec[:80])
    head2, sec2 = k.retrieve("大叔胁迫剧情")
    check("命中胁迫章节", "14.7 胁迫" in sec2)

    print("[3] 画师库")
    ap = TBArtistPicker(cfg)
    ok, msg = ap.ensure_data()
    check("画师库就绪", ok, msg)
    hits = ap.search("dairi", top=3)
    check("检索 dairi", bool(hits) and hits[0].get("name") == "dairi")
    tags = ap.build_artist_tags(named=hits[:1])
    check("画师串 @dairi", tags.startswith("@dairi"), tags[:40])

    print("[4] 最小原生图报文")
    g = TBComfyBase(cfg).build_graph("test", "neg", 1024, 1024, seed=42)
    check("10 节点(含 ModelSamplingAuraFlow)",
          sorted(int(k) for k in g) == list(range(1, 11)) and "10" in g)
    check("UNET 参数", g["1"]["class_type"] == "UNETLoader" and
          g["1"]["inputs"]["unet_name"] == "anima_baseV10.safetensors")
    check("CLIP qwen_image", g["2"]["inputs"]["type"] == "qwen_image")
    check("Shift 偏移链接", g["10"]["class_type"] == "ModelSamplingAuraFlow" and
          g["10"]["inputs"]["model"] == ["1", 0] and g["7"]["inputs"]["model"] == ["10", 0])
    check("KSampler 链接", g["7"]["inputs"]["positive"] == ["4", 0] and
          g["7"]["inputs"]["latent_image"] == ["6", 0])

    print("[5] 归档命名/元数据")
    tmp = tempfile.mkdtemp(prefix="paint_test_")
    ar = TBPainterArchive(os.path.join(tmp, "paints"))
    src = os.path.join(tmp, "img.png")
    open(src, "wb").write(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    import json
    ok, folder, final = ar.save("黑长直美女_自慰", src,
                                meta={"positive": "1girl", "reply": "画好啦"})
    check("归档成功", ok and os.path.isfile(final))
    m = json.load(open(os.path.join(folder, "meta.json"), encoding="utf-8"))
    check("meta 含标题与正提示词", m.get("title") == "黑长直美女_自慰" and "positive" in m)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("离线自检：" + ("全部通过 ✅" if ok_all else "存在失败项 ❌"))
    return 0 if ok_all else 1


def live_paint():
    # 端到端真画（默认：画一个黑长直美女在自慰）
    request = " ".join(sys.argv[1:]).strip() or "画一个黑长直美女在自慰"
    print(f"[flux 端到端] 请求：{request}")
    from func.toolbox.flux_painter.config import TBFluxPainterConfig
    from func.toolbox.flux_painter.painting_core import TBFluxPainterCore
    from func.log.default_log import DefaultLog

    cfg = TBFluxPainterConfig()
    if not cfg.enabled:
        print("[错误] flux_painter.enabled=false（config.yml）")
        return 1
    if not cfg.active_llm().get("api_key"):
        print("[错误] 提示词 LLM 未配置 api_key")
        return 1

    core = TBFluxPainterCore()
    core.set_username("主人")
    core.set_context({"username": "主人", "text": request,
                      "short_memory": [], "system_prompt": ""})
    print("[1] 触发 flux_paint …")
    ret = core.dispatch("flux_paint", {"request": request, "topic": "测试画"})
    print(f"     dispatch → {ret}")
    wait = 0
    while core.is_painting() and wait < 900:
        time.sleep(2)
        wait += 2
        if wait % 20 == 0:
            print(f"     …等待绘画中 {wait}s")
    print(f"[2] 绘画线程结束（{wait}s）")
    # 最新归档目录
    backup = cfg.backup_dir
    dirs = []
    if os.path.isdir(backup):
        dirs = sorted([os.path.join(backup, d) for d in os.listdir(backup)
                       if os.path.isdir(os.path.join(backup, d))], key=os.path.getmtime)
    if dirs:
        latest = dirs[-1]
        img = os.path.join(latest, "image.png")
        print(f"[3] 最新画作：{latest}")
        print(f"     图文件存在: {os.path.isfile(img)} | 大小 {os.path.getsize(img) if os.path.isfile(img) else 0}B")
        print(f"     画板查看: http://127.0.0.1:{cfg.http_port}/painting_board.html")
        return 0 if os.path.isfile(img) else 1
    print("[3] 未发现归档画作（请查看日志/画板）")
    return 1


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else live_paint())
