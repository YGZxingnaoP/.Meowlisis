# -*- coding: utf-8 -*-
# scripts/gen_plugin_cards.py
# 生成插件区卡面：1 张「插件」父卡 + 每个插件 1 张卡
# 风格（底模/采样/正向风格前缀/负向）从 gui/resource/cat_photos 的官方卡面 PNG 元数据中提取，
# 保证与内置卡面风格一致；成品写入 plugins/card.png 与 plugins/<插件id>/card.png
# 运行：runtime\python.exe scripts\gen_plugin_cards.py [插件id ...]

import json
import os
import struct
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from func.toolbox.flux_painter.config import TBFluxPainterConfig
from func.toolbox.flux_painter.comfy_connector.base import TBComfyBase

REF_DIR = os.path.join(BASE_DIR, "gui", "resource", "cat_photos")
PLUGINS_DIR = os.path.join(BASE_DIR, "plugins")
CARD_SIZE = (832, 1152)
PLUGIN_SELF = ("plugins", "docwriter", "epub_reader")

# 兜底风格（参考图缺失时使用，内容与官方卡面一致）
FALLBACK_PREFIX = (
    "masterpiece, very aesthetic, best quality, score_9, score_8_up, score_7_up, highres, "
    "absurdres, anime screenshot, official art, cute anime illustration, kawaii, moe, adorable, "
    "lovable, soft pastel color palette, gentle soft shading, clean crisp lineart, "
    "big sparkling glossy eyes, round soft cheeks, small cute mouth, trading card art, "
    "@free_style_(yohan1754), 1girl, solo, catgirl, cat ears, cat tail, white hair, long hair, "
    "curly hair, wavy hair, long softly curled white hair, yellow eyes, bright golden-yellow eyes, "
    "a blue butterfly hair ornament pinned on the left side of her hair, "
    "blue butterfly hair ornament on the left, white blouse, JK uniform, pleated skirt, "
)
FALLBACK_SUFFIX = (
    " at viewer, soft rim light, plain pure white background, sharp focus, highly detailed, "
    "single subject, simple clean composition, blue butterfly hair ornament on the left side of her hair"
)
FALLBACK_NEGATIVE = (
    "lowres,bad,error,fewer,extra,missing,worst quality,jpeg artifacts,bad quality,watermark,"
    "signature,extra digits,artistic error,username,abstract,artist logo,artist name,bad fingers,"
    "bad hand,patreon username,patreon logo,web address,(worst quality, low quality:1.4),"
    "(deformed, distorted, disfigured:1.3),poorly drawn hands,extra fingers,mutated,messy drawing,"
    "doll,plastic skin,fat,abs,old,2girl,fat girl,very long leg,very long thigh,pale skin,bad anatomy,"
    "inverted limbs,missing leg,missing arm,extra leg,extra arm,crowd,deformed,sharp teeth,expressionless,"
    "Mosaic,butterfly hair ornament on the right side,hair ornament on the wrong side,two hair ornaments,"
    "symmetric hair ornaments,hair ornament in the middle of her head,hair ribbon,ribbon bow,hair bow,bow,"
    "hairband,headband,cluttered background,busy composition,multiple characters,extra objects,realistic,"
    "photorealistic,3d,gloomy,dark,blonde hair,black hair,brown hair,pink hair,orange hair,silver hair,"
    "short hair,straight hair,buzz cut,red eyes,blue eyes,green eyes,brown eyes,purple eyes,pink eyes,"
    "black eyes,colored background,gradient background,scenery,complex background,multiple views,collage,"
    "split screen,cropped face,cut off head"
)

CARDS = [
    {
        "id": "plugins", "label": "插件（父卡）", "path": os.path.join(PLUGINS_DIR, "card.png"),
        "scene": "holding a glowing puzzle piece up in one hand and a small toolbox in the other, "
                 "smiling brightly at it, mustard yellow knit cardigan, soft golden and blue sparkle glow "
                 "accents, cheerful mood, upper body, front view, leaning toward the camera, "
                 "bright confident smile",
    },
    {
        "id": "docwriter", "label": "文档助手",
        "path": os.path.join(PLUGINS_DIR, "docwriter", "card.png"),
        "scene": "holding a fountain pen up in one hand with floating sheets of paper around the other, "
                 "winking at it, beige knit cardigan slipping off one shoulder, warm beige and blue sparkle "
                 "glow accents, focused happy mood, upper body, front view, leaning toward the camera, "
                 "confident playful wink",
    },
    {
        "id": "epub_reader", "label": "读书助手",
        "path": os.path.join(PLUGINS_DIR, "epub_reader", "card.png"),
        "scene": "hugging a thick open book to her chest with both arms, smiling softly at it, "
                 "cream duffle coat with wooden toggles, warm cream and blue sparkle glow accents, "
                 "cozy gentle mood, upper body, three-quarter view from her right, head tilted, "
                 "gentle tender smile",
    },
]


def png_prompt(path):
    """读取 PNG 内嵌的 ComfyUI prompt 图（PNG tEXt/iTXt 块）"""
    try:
        with open(path, "rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return None
            while True:
                head = f.read(8)
                if len(head) < 8:
                    return None
                length, ctype = struct.unpack(">I4s", head)
                data = f.read(length)
                f.read(4)
                if ctype == b"tEXt":
                    key, _, val = data.partition(b"\x00")
                    if key == b"prompt":
                        return json.loads(val.decode("utf-8", errors="ignore"))
                elif ctype == b"IEND":
                    return None
    except Exception:
        return None


def graph_texts(graph):
    """取正向/负向文本"""
    samplers = [n for n in graph.values() if n.get("class_type") == "KSampler"]
    if not samplers:
        return "", ""

    def text_of(ref):
        node = graph.get(str(ref[0])) if isinstance(ref, list) else None
        if node and node.get("class_type") == "CLIPTextEncode":
            return node["inputs"].get("text", "")
        return ""

    return text_of(samplers[0]["inputs"].get("positive")), text_of(samplers[0]["inputs"].get("negative"))


def load_style():
    """从官方卡面提取风格：模型/采样/正向公共前缀与后缀/负向"""
    positives, negatives, graphs = [], [], []
    if os.path.isdir(REF_DIR):
        for name in sorted(os.listdir(REF_DIR)):
            if not name.endswith(".png") or os.path.splitext(name)[0] in PLUGIN_SELF:
                continue
            graph = png_prompt(os.path.join(REF_DIR, name))
            if not graph:
                continue
            pos, neg = graph_texts(graph)
            if pos:
                positives.append(pos)
                negatives.append(neg)
                graphs.append(graph)
    if not positives:
        print("未找到官方卡面参考，使用内置兜底风格")
        return {"prefix": FALLBACK_PREFIX, "suffix": FALLBACK_SUFFIX,
                "negative": FALLBACK_NEGATIVE, "graph": None}
    prefix = os.path.commonprefix(positives)
    suffix = os.path.commonprefix([p[::-1] for p in positives])[::-1]
    negative = max(set(negatives), key=negatives.count)
    print(f"参考官方卡面 {len(positives)} 张，公共前缀 {len(prefix)} 字，公共后缀 {len(suffix)} 字")
    return {"prefix": prefix, "suffix": suffix, "negative": negative, "graph": graphs[0]}


def first_node(graph, class_type):
    """取某类节点的输入（无则空）"""
    for node in (graph or {}).values():
        if node.get("class_type") == class_type:
            return node["inputs"]
    return {}


def build_graph(style, positive):
    """按官方图结构构造 API 图（同底模 / 同 LoRA / 同采样）"""
    ref = style.get("graph") or {}
    unet = first_node(ref, "UNETLoader").get("unet_name", "miaomiaoHarem_anima16.safetensors")
    clip = first_node(ref, "CLIPLoader")
    vae = first_node(ref, "VAELoader").get("vae_name", "qwen_image_vae.safetensors")
    lora = first_node(ref, "LoraLoaderModelOnly")
    sampler_in = first_node(ref, "KSampler")
    shift_in = first_node(ref, "ModelSamplingAuraFlow")
    latent = first_node(ref, "EmptyLatentImage")
    width = int(latent.get("width") or CARD_SIZE[0])
    height = int(latent.get("height") or CARD_SIZE[1])

    graph = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": clip.get("clip_name", "anima_baseV10_txt.safetensors"),
                         "type": clip.get("type", "stable_diffusion")}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": style["negative"], "clip": ["2", 0]}},
        "6": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "plugin_card"}},
    }
    model_src = ["1", 0]
    if lora:
        graph["20"] = {"class_type": "LoraLoaderModelOnly",
                       "inputs": {"lora_name": lora.get("lora_name", ""),
                                  "strength_model": float(lora.get("strength_model", 0.5)),
                                  "model": ["1", 0]}}
        model_src = ["20", 0]
    shift = float(shift_in.get("shift", 3.0))
    graph["10"] = {"class_type": "ModelSamplingAuraFlow",
                   "inputs": {"model": model_src, "shift": shift}}
    graph["7"] = {"class_type": "KSampler",
                  "inputs": {"model": ["10", 0], "positive": ["4", 0], "negative": ["5", 0],
                             "latent_image": ["6", 0], "seed": 0,
                             "steps": int(sampler_in.get("steps", 30)),
                             "cfg": float(sampler_in.get("cfg", 5.0)),
                             "sampler_name": sampler_in.get("sampler_name", "er_sde"),
                             "scheduler": sampler_in.get("scheduler", "simple"),
                             "denoise": 1.0}}
    return graph


def generate(comfy, style, card):
    """提交一次生成并取回本地图片路径"""
    name = card["id"]
    positive = style["prefix"] + card["scene"] + style["suffix"]
    graph = build_graph(style, positive)
    graph["9"]["inputs"]["filename_prefix"] = "plugin_card_" + name
    ok, prompt_id, msg = comfy.submit(graph)
    if not ok:
        print(f"  [{name}] 提交失败: {msg}")
        return ""
    print(f"  [{name}] 已提交 prompt_id={prompt_id}，等待生成…")
    ok, images, msg = comfy.wait(prompt_id, timeout=900)
    if not ok or not images:
        print(f"  [{name}] 生成失败: {msg}")
        return ""
    paths = comfy.images_local(images)
    if not paths:
        print(f"  [{name}] 图片下载失败")
        return ""
    return paths[-1]


def main():
    """读取官方卡面风格 → 生成插件卡面到插件目录"""
    only = set(sys.argv[1:])
    cfg = TBFluxPainterConfig()
    comfy = TBComfyBase(cfg)
    print(f"ComfyUI: {comfy.base_url()}  尺寸: {CARD_SIZE[0]}x{CARD_SIZE[1]}")
    style = load_style()
    targets = [c for c in CARDS if not only or c["id"] in only]
    print("待生成卡面: " + ", ".join(c["id"] for c in targets))
    if not comfy.health():
        print("无法连接 ComfyUI：请确认云端 8188 已开启，并检查 config.yml 的 flux_painter.comfy.host / port")
        return 1
    for card in targets:
        print(f"生成卡面: {card['id']}（{card['label']}）")
        src = generate(comfy, style, card)
        if src:
            os.makedirs(os.path.dirname(card["path"]), exist_ok=True)
            import shutil
            shutil.copyfile(src, card["path"])
            print(f"  [{card['id']}] 卡面已保存: {card['path']}")
    print(f"完成，共处理 {len(targets)} 张")
    return 0


if __name__ == "__main__":
    sys.exit(main())
