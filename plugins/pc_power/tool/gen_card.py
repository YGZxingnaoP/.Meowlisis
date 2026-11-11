# -*- coding: utf-8 -*-
"""用 ComfyUI 生成睡前关机插件的卡面 card.png。

工作流直接复用 plugins/card.png 内嵌的 prompt（与其它插件同一角色/画风/尺寸），
只替换「trading card art, 」之后的描述，并加入纹理材质细节。

用法：
    python gen_card.py check
    python gen_card.py submit
    python gen_card.py fetch [等待秒数]
"""

import json
import os
import random
import sys
import tempfile
import time

import requests
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "http://127.0.0.1:8188"
ROOT = r"D:\.Meowlisis"
TEMPLATE_CARD = os.path.join(ROOT, "plugins", "card.png")
OUT_CARD = os.environ.get("PC_POWER_CARD_OUT") or \
    os.path.join(ROOT, "plugins", "pc_power", "card.png")
TMP = tempfile.gettempdir()
PID_FILE = os.path.join(TMP, "pc_power_card_pid.txt")
WF_FILE = os.path.join(TMP, "pc_power_card_workflow.json")

CARD_DESC = (
    "@free_style_(yohan1754), 1girl, solo, catgirl, cat ears, cat tail, "
    "white hair, long hair, curly hair, wavy hair, long softly curled white hair, "
    "yellow eyes, bright golden-yellow eyes, "
    "a blue butterfly hair ornament pinned on the left side of her hair, "
    "blue butterfly hair ornament on the left, "
    "white blouse, JK uniform, pleated skirt, "
    "a cozy pale-blue knitted cardigan slipping off one shoulder, "
    "holding a glowing crescent-moon shaped power switch in both hands, "
    "a tiny sleeping black cat plush tucked against her arm, "
    "soft blue moonlight and warm amber lamp glow, sleepy gentle mood, "
    "brushed metal texture on the switch, woven knit fabric texture, "
    "embossed border pattern, fine paper grain texture, matte laminate finish, "
    "subtle foil accents, tactile material details, "
    "upper body, front view, leaning toward the camera, gentle sleepy smile at viewer, "
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
    """读模板卡面内嵌工作流，替换正向提示词 / 种子 / 输出前缀"""
    info = Image.open(TEMPLATE_CARD).info or {}
    raw = info.get("prompt")
    if not raw:
        raise SystemExit("模板 plugins/card.png 里没有 prompt 元数据")
    wf = json.loads(raw)
    base = wf["4"]["inputs"]["text"]
    head = base.split("trading card art, ")[0] + "trading card art, "
    wf["4"]["inputs"]["text"] = head + CARD_DESC
    wf["7"]["inputs"]["seed"] = random.randint(1, 2 ** 31 - 1)
    wf["9"]["inputs"]["filename_prefix"] = "plugin_card_pc_power"

    lora = wf.get("20", {}).get("inputs", {}).get("lora_name")
    if lora and lora not in _available("LoraLoaderModelOnly", "lora_name"):
        wf["10"]["inputs"]["model"] = ["1", 0]
        wf.pop("20", None)
        wf["_note"] = "LoRA %s 不可用，已自动绕过" % lora
    return wf


def check():
    wf = build_workflow()
    if wf.get("_note"):
        print("[" + wf["_note"] + "]")
    print("正向提示词：\n  " + wf["4"]["inputs"]["text"])
    print("\n尺寸：", wf["6"]["inputs"]["width"], "x", wf["6"]["inputs"]["height"])
    print("采样：", {k: wf["7"]["inputs"][k] for k in
                     ("steps", "cfg", "sampler_name", "scheduler", "denoise")})
    try:
        oi = requests.get(HOST + "/object_info", timeout=10).json()
    except Exception as e:
        print("\n[×] 连不上 ComfyUI：", e)
        return False
    for node, key, val in (("UNETLoader", "unet_name", wf["1"]["inputs"]["unet_name"]),
                           ("CLIPLoader", "clip_name", wf["2"]["inputs"]["clip_name"]),
                           ("VAELoader", "vae_name", wf["3"]["inputs"]["vae_name"])):
        opts = (((oi.get(node) or {}).get("input") or {}).get("required") or {}).get(key) or []
        choices = opts[0] if opts and isinstance(opts[0], list) else []
        ok = val in choices
        print("%s %s: %s  (%d 个可用)" % ("[√]" if ok else "[×]", node, val, len(choices)))
        if not ok:
            print("  可用样例：", choices[:5])
    return True


def submit():
    wf = build_workflow()
    r = requests.post(HOST + "/prompt", json={"prompt": wf, "client_id": "pcpower_card"}, timeout=30)
    data = r.json()
    if r.status_code != 200 or "prompt_id" not in data:
        print("[×] 提交失败:", json.dumps(data, ensure_ascii=False)[:800])
        return None
    pid = data["prompt_id"]
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(pid)
    with open(WF_FILE, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False)
    print("[√] 已提交，prompt_id =", pid, "\n    种子 =", wf["7"]["inputs"]["seed"])
    return pid


def fetch(pid=None, wait=180):
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
        w = int(sys.argv[2]) if len(sys.argv) > 2 else 180
        fetch(wait=w)
    else:
        print(__doc__)
