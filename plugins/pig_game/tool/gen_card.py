# -*- coding: utf-8 -*-
"""用 ComfyUI 为养猪游戏生成插件卡面 card.png（复用其它插件卡面的同一套工作流）。

用法：
    python gen_card.py check      # 检查模型/LoRA 是否齐全 + 打印将要使用的提示词
    python gen_card.py submit     # 提交任务，记录 prompt_id
    python gen_card.py fetch      # 轮询并下载成品 → plugins/pig_game/card.png
"""

import json
import os
import random
import sys
import time

import requests
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "http://127.0.0.1:8188"
ROOT = r"D:\.Meowlisis"
TEMPLATE_CARD = os.path.join(ROOT, "plugins", "card.png")          # 复用它的内嵌工作流
OUT_CARD = os.path.join(ROOT, "plugins", "pig_game", "card.png")
TMP = os.path.join(ROOT, "plugins", "_tmp")
PID_FILE = os.path.join(TMP, "pig_card_pid.txt")
WF_FILE = os.path.join(TMP, "pig_card_workflow.json")

# 与其它插件卡面保持同一角色/画风，只换服装与道具（养猪主题）
PIG_DESC = (
    "@free_style_(yohan1754), 1girl, solo, catgirl, cat ears, cat tail, "
    "white hair, long hair, curly hair, wavy hair, long softly curled white hair, "
    "yellow eyes, bright golden-yellow eyes, "
    "a blue butterfly hair ornament pinned on the left side of her hair, "
    "blue butterfly hair ornament on the left, "
    "white blouse, JK uniform, pleated skirt, pink farm overalls with a small pig snout patch, "
    "cradling a chubby pink plush piglet in both arms, nuzzling it happily, "
    "holding a tiny wooden feed bucket in one hand, "
    "soft pink and blue sparkle glow accents, cheerful doting mood, "
    "upper body, front view, leaning toward the camera, bright happy smile at viewer, "
    "soft rim light, plain pure white background, sharp focus, highly detailed, "
    "single subject, simple clean composition, "
    "blue butterfly hair ornament on the left side of her hair"
)


def _available(node, key):
    try:
        oi = requests.get(HOST + "/object_info/" + node, timeout=20).json()
        opts = ((oi.get(node) or {}).get("input") or {}).get("required") or {}
        lst = opts.get(key) or []
        return list(lst[0]) if lst and isinstance(lst[0], list) else []
    except Exception:
        return []


def build_workflow():
    """读取 plugins/card.png 内嵌工作流，替换正向提示词 / 种子 / 前缀。

    若当前 ComfyUI 里没有同款 LoRA，则自动绕过 LoRA 节点（其余完全一致）。
    """
    info = Image.open(TEMPLATE_CARD).info or {}
    raw = info.get("prompt")
    if not raw:
        raise SystemExit("模板 plugins/card.png 里没有 prompt 元数据")
    wf = json.loads(raw)
    base = wf["4"]["inputs"]["text"]
    head = base.split("trading card art, ")[0] + "trading card art, "
    wf["4"]["inputs"]["text"] = head + PIG_DESC
    wf["7"]["inputs"]["seed"] = random.randint(1, 2 ** 31 - 1)
    wf["9"]["inputs"]["filename_prefix"] = "plugin_card_pig_game"

    lora = wf.get("20", {}).get("inputs", {}).get("lora_name")
    if lora and lora not in _available("LoraLoaderModelOnly", "lora_name"):
        wf["10"]["inputs"]["model"] = wf["1"] and ["1", 0]     # 直接接 UNET
        wf.pop("20", None)
        wf["_note"] = "LoRA %s 不可用，已自动绕过" % lora
    return wf


def check():
    wf = build_workflow()
    if wf.get("_note"):
        print("[" + wf["_note"] + "]")
    print("正向提示词：\n  " + wf["4"]["inputs"]["text"])
    print("\n负向提示词（前 120 字）：\n  " + wf["5"]["inputs"]["text"][:120] + "…")
    print("\n采样：", {k: wf["7"]["inputs"][k] for k in
                      ("steps", "cfg", "sampler_name", "scheduler", "denoise")})
    print("尺寸：", wf["6"]["inputs"]["width"], "x", wf["6"]["inputs"]["height"])
    print("种子：", wf["7"]["inputs"]["seed"])
    try:
        oi = requests.get(HOST + "/object_info", timeout=10).json()
    except Exception as e:
        print("\n[×] 连不上 ComfyUI：", e)
        return False
    for node, key, val in (("UNETLoader", "unet_name", wf["1"]["inputs"]["unet_name"]),
                           ("CLIPLoader", "clip_name", wf["2"]["inputs"]["clip_name"]),
                           ("VAELoader", "vae_name", wf["3"]["inputs"]["vae_name"]),
                           ("LoraLoaderModelOnly", "lora_name", wf["20"]["inputs"]["lora_name"])):
        opts = (((oi.get(node) or {}).get("input") or {}).get("required") or {}).get(key) or []
        choices = opts[0] if opts and isinstance(opts[0], list) else []
        ok = val in choices
        print("%s %s: %s  (%d 个可用)" % ("[√]" if ok else "[×]", node, val, len(choices)))
    return True


def submit():
    wf = build_workflow()
    os.makedirs(TMP, exist_ok=True)
    with open(WF_FILE, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False)
    r = requests.post(HOST + "/prompt", json={"prompt": wf, "client_id": "piggame_card"}, timeout=30)
    data = r.json()
    if r.status_code != 200 or "prompt_id" not in data:
        print("[×] 提交失败:", json.dumps(data, ensure_ascii=False)[:800])
        return None
    pid = data["prompt_id"]
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(pid)
    print("[√] 已提交，prompt_id =", pid, "\n    种子 =", wf["7"]["inputs"]["seed"])
    return pid


def fetch(pid=None, wait=150):
    if not pid and os.path.isfile(PID_FILE):
        pid = open(PID_FILE, encoding="utf-8").read().strip()
    if not pid:
        print("[×] 没有 prompt_id，先 submit")
        return False
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            h = requests.get(HOST + "/history/" + pid, timeout=10).json()
        except Exception as e:
            print("  轮询异常:", e)
            time.sleep(3)
            continue
        entry = h.get(pid)
        if entry:
            imgs = []
            for node in (entry.get("outputs") or {}).values():
                imgs.extend(node.get("images") or [])
            if entry.get("status", {}).get("status_str") == "error":
                print("[×] 执行出错:", json.dumps(entry.get("status"), ensure_ascii=False)[:600])
                return False
            if imgs:
                info = imgs[0]
                params = {"filename": info["filename"],
                          "subfolder": info.get("subfolder", ""),
                          "type": info.get("type", "output")}
                raw = requests.get(HOST + "/view", params=params, timeout=60).content
                os.makedirs(os.path.dirname(OUT_CARD), exist_ok=True)
                with open(OUT_CARD, "wb") as f:
                    f.write(raw)
                im = Image.open(OUT_CARD)
                print("[√] 已生成 →", OUT_CARD, im.size, "%d KB" % (len(raw) // 1024))
                return True
        time.sleep(4)
    print("… 还没跑完（可稍后再执行 fetch）")
    return False


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "check":
        check()
    elif mode == "submit":
        check()
        submit()
    elif mode == "fetch":
        w = int(sys.argv[2]) if len(sys.argv) > 2 else 150
        fetch(wait=w)
    else:
        print(__doc__)
