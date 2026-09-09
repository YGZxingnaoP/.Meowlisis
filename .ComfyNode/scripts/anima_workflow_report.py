# -*- coding: utf-8 -*-
# .ComfyNode/scripts/anima_workflow_report.py
# 解析 .ComfyNode/node/Anima正式版-文生图工作流.json，输出可读链路报告
# 用法：python -X utf8 .ComfyNode/scripts/anima_workflow_report.py
import io, json, os, re, collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WF = os.path.join(ROOT, ".ComfyNode", "node", "Anima正式版-文生图工作流.json")
DATA_JS = r"D:\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes\Comfyui-Anima-Tools-main\js\data.js"

d = json.load(io.open(WF, encoding="utf-8"))
nodes = {n["id"]: n for n in d["nodes"] if isinstance(n, dict) and n.get("id") is not None}
links = d.get("links") or []
WIDGET_ROLE = {"CR Prompt Text": "文本源", "CLIPTextEncode": "文本编码",
               "KSampler": "采样", "VAELoader": "VAE", "CLIPLoader": "CLIP",
               "UNETLoader": "模型", "EmptyLatentImage": "尺寸", "VAEDecode": "解码",
               "SaveImage": "存图", "ShowText|pysssss": "文本预览",
               "UltimateSDUpscale": "放大", "UpscaleModelLoader": "放大模型",
               "JoinStringMulti": "拼串", "LoraLoaderModelOnly": "Lora",
               "ModelSamplingAuraFlow": "采样偏移", "Fast Groups Bypasser (rgthree)": "分组旁路"}

print("=" * 72)
print("工作流文件:", os.path.basename(WF))
print("节点总数:", len(nodes), "| 连线总数:", len(links))
print("=" * 72)

groups = d.get("groups") or []
print("\n[分组/Groups]")
for g in groups:
    flag = "◐" if (g.get("flags") or {}).get("collapsed") else ""
    print(f"  - {g.get('title')}  nodes={g.get('nodes')} {flag}")

print("\n[节点清单（按类型）]")
tcount = collections.Counter(n["type"] for n in nodes.values())
for t, c in tcount.most_common():
    print(f"  {t} x{c}   <- {WIDGET_ROLE.get(t, '自定义/其他')}")

print("\n[关键节点参数]")
for n in nodes.values():
    t = n.get("type")
    wv = n.get("widgets_values")
    if t in ("CR Prompt Text", "LoraLoaderModelOnly", "JoinStringMulti",
             "CLIPTextEncode", "KSampler", "EmptyLatentImage", "UNETLoader",
             "VAELoader", "CLIPLoader", "UpscaleModelLoader", "ShowText|pysssss"):
        title = n.get("title") or t
        print(f"  #{n['id']} {t} | {title}")
        print(f"       values: {json.dumps(wv, ensure_ascii=False)[:300]}")

print("\n[文本流正向链路] (找 ShowText / SaveImage 的输入端逐级回溯)")
def feed(node_id, depth=0):
    n = nodes.get(node_id)
    if not n or depth > 4:
        return
    inds = {}
    for inp in n.get("inputs") or []:
        if inp.get("link") is not None:
            inds[inp.get("name")] = inp["link"]
    print("  " * depth + f"→ #{n['id']} {n.get('type')} {n.get('title') or ''}")
    if n.get("widgets_values"):
        print("  " * depth + f"    widgets: {json.dumps(n.get('widgets_values'), ensure_ascii=False)[:260]}")
    for lk in links:
        if len(lk) > 4 and lk[3] in inds.values():
            feed(lk[1], depth + 1)
            break

for n in nodes.values():
    if n.get("type") in ("ShowText|pysssss", "SaveImage"):
        print(f"\n--- {n.get('type')} #{n['id']} 上游 ---")
        feed(n["id"])

print("\n[正/负文本链路（LiteGraph: [id, src, src_slot, dst, dst_slot, type]）]")
# 由目标节点 input.link 找源 link：link_id == input.link
def source_of_link(link_id):
    for lk in links:
        if len(lk) > 4 and lk[0] == link_id:
            return lk[1]  # 源节点id
    return None

def brief(nid):
    n = nodes.get(nid)
    return f"#{nid} {n.get('type') if n else '?'} {n.get('title') or ''}"

for n in nodes.values():
    if n.get("type") != "CLIPTextEncode":
        continue
    role = "负向" if "Negative" in (n.get("title") or "") else "正向"
    print(f"\n--- #{n['id']} CLIPTextEncode ({role}) ---")
    text_src = None
    for inp in n.get("inputs") or []:
        if inp.get("link") is not None:
            s = source_of_link(inp["link"])
            if s is not None:
                print(f"  [{inp['name']}] <- {brief(s)}")
                if inp.get("name") == "text":
                    text_src = s
    if text_src is not None and nodes.get(text_src, {}).get("type") == "JoinStringMulti":
        js = nodes.get(text_src)
        # JoinString 的 inputs 顺序 = 最终拼接顺序
        for inp in js.get("inputs") or []:
            s = source_of_link(inp["link"]) if inp.get("link") is not None else None
            src = nodes.get(s)
            if src:
                print(f"      拼接slot[{inp['name']}] = 「{src.get('title') or src.get('type')}」 "
                      f"values={json.dumps(src.get('widgets_values'), ensure_ascii=False)[:200]}")
            else:
                print(f"      拼接slot[{inp['name']}] = (无上游/内嵌)")

print("\n[采样/尺寸/放大/存图]")
for n in nodes.values():
    t = n.get("type")
    if t in ("KSampler", "EmptyLatentImage", "UpscaleModelLoader", "SaveImage", "Fast Groups Bypasser (rgthree)"):
        print(f"  {brief(n['id'])} values={json.dumps(n.get('widgets_values'), ensure_ascii=False)[:200]}")

print("\n[画师库 data.js 结构]")
if os.path.exists(DATA_JS):
    s = io.open(DATA_JS, encoding="utf-8", errors="ignore").read()
    head = s[s.find("["):s.find("[") + 700]
    cnt = re.findall(r'"name":\s*"', s)
    print(f"  文件大小: {len(s)/1024/1024:.1f} MB | 画师条目约: {len(cnt)}")
    print("  结构样本:", head[:400].replace(chr(10), " "))
else:
    print("  未找到 data.js:", DATA_JS)
