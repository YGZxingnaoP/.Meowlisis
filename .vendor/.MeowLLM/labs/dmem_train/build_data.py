# -*- coding: utf-8 -*-
"""把项目已有数据合成 δ-mem 的 SFT 训练集（context, query, response）。

为什么要合成
------------
δ-mem 的样本必须满足"答案只能从 context 推出"，因为 context 写进状态后
**从 backbone 输入里删掉**（论文 §3.6）。闲聊回复不依赖历史，训出来等于没训：
模型最省力的解是把修正量 αΔq 压到 0，loss 照样降，记忆通路学不到东西。

数据来源（按重要性）
--------------------
    character/abstract_memory/*.json   记忆事件（主力）
    character/userinfo/*.json          用户档案（偏好/人称）
    .temp/*_record.txt                 真实对话轮次（语气，少量）
    （可选）HotpotQA / LoCoMo          和论文数字对齐用

两种合成方式
------------
    --mode template   离线零成本：用事件标签套问题模板，答案=事件原文
    --mode llm        调 config.yml 里已有的端点，让教师模型写"只读记忆才能答"的问答对

用法
----
    python build_data.py --mode template --limit 2000
    python build_data.py --mode llm --limit 20000 --workers 8
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_ROOT = os.path.dirname(os.path.dirname(HERE))     # 本地：.vendor/.MeowLLM


def _detect_project() -> str:
    """找"项目根"：从本文件往上，第一个含 `character/abstract_memory` 的目录。

    为什么要探测而不是写死：本地布局是 `<项目>/.vendor/.MeowLLM/labs/dmem_train`（上 4 层），
    云端上传后是 `<项目>/labs/dmem_train`（上 2 层）。写死路径在云端会指到 `/root`。
    """
    current = HERE
    for _ in range(6):
        if os.path.isdir(os.path.join(current, "character", "abstract_memory")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.path.dirname(os.path.dirname(MODULE_ROOT))   # 兜底：老结构


PROJECT_ROOT = _detect_project()

sys.path.insert(0, HERE)
from dataset import write_jsonl  # noqa: E402

DEFAULT_ABMEM = os.path.join(PROJECT_ROOT, "character", "abstract_memory")
DEFAULT_USERINFO = os.path.join(PROJECT_ROOT, "character", "userinfo")
DEFAULT_RECORD = os.path.join(PROJECT_ROOT, ".temp")
DEFAULT_OUT = os.path.join(HERE, "data", "sft.jsonl")

NEUTRAL_QUERIES = [
    "你现在在做什么呀？",
    "今天心情怎么样？",
    "给我讲一句你常说的话。",
    "你怎么看熬夜这件事？",
    "你会唱歌吗？",
    "如果我现在叫你去睡觉，你会怎么回？",
]


def event_id(text: str) -> str:
    """事件文本指纹，用于 train/holdout 分组，防止同一事件两边都有。"""
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------ 读
def load_events(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = str(item.get("event") or "").strip()
        if len(text) < 8:
            continue
        out.append({
            "event": text,
            "eid": event_id(text),
            "tags": [str(t) for t in (item.get("tags") or []) if str(t).strip()],
            "topics": [str(t) for t in (item.get("topics") or []) if str(t).strip()],
            "importance": float(item.get("importance") or 0),
            "accuracy": int(item.get("accuracy") or 0),
        })
    return out


def load_userinfo(folder: str) -> list[dict]:
    """userinfo 下 `index.json` 是映射表，其余是按 uid 的档案。"""
    rows: list[dict] = []
    if not os.path.isdir(folder):
        return rows
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json") or name == "index.json":
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:  # noqa: BLE001
            continue
        rows.append({"uid": name[:-5], "data": data})
    return rows


def load_records(folder: str) -> list[list[tuple[str, str]]]:
    """短时记忆轮次记录：`[时间][说话人]: 内容`（GBK 编码）。"""
    dialogs = []
    if not os.path.isdir(folder):
        return dialogs
    for name in sorted(os.listdir(folder)):
        if not name.endswith("_record.txt"):
            continue
        try:
            raw = open(os.path.join(folder, name), "rb").read().decode("gbk", "ignore")
        except Exception:  # noqa: BLE001
            continue
        turns = re.findall(r"^\[[^\]]+\]\[([^\]]+)\]:\s*(.+)$", raw, re.M)
        if len(turns) >= 2:
            dialogs.append([(a.strip(), b.strip()) for a, b in turns if b.strip()])
    return dialogs


# ------------------------------------------------------------------ 合成
def template_pairs(events: list[dict], rng: random.Random) -> list[dict]:
    rows = []
    for ev in events:
        tag = (ev["tags"] or ev["topics"] or [""])[0]
        if not tag:
            continue
        query = rng.choice([
            f"我之前是不是跟你提过「{tag}」的事？具体是怎么回事？",
            f"关于「{tag}」，你还记得多少？",
            f"我把「{tag}」那件事讲给你听过吧，说说看。",
        ])
        rows.append({"query": query, "response": ev["event"], "event": ev})
    return rows


LLM_PROMPT = """你是一个数据集构造器。下面给你一组「记忆条目」，它们是角色对主人的长期记忆。
请基于其中**一条**写一个问答对，要求：
1. 问题要像主人自然的口语提问，不能出现「记忆条目」「根据资料」这类字眼；
2. 答案必须**只能**从记忆条目推出（不能是通用常识，也不能靠猜）；
3. 答案简短，40 字以内，用角色的口吻；
4. 如果这条记忆本身不足以支撑一个明确答案，输出 null。
只输出 JSON：{"query": "...", "response": "...", "used_index": 0}
记忆条目：
{items}"""


def pick_llm_node(cfg: dict) -> dict | None:
    for node in (cfg.get("llm") or {}).values():
        if (isinstance(node, dict) and node.get("api_key") and node.get("base_url")
                and "deepseek" in str(node.get("base_url"))):
            return node
    return None


def llm_pairs(events: list[dict], cfg: dict, rng: random.Random,
              workers: int = 4, batch: int = 6) -> list[dict]:
    try:
        from openai import OpenAI
    except Exception as exc:  # noqa: BLE001
        print(f"openai 包不可用（{exc}），退回模板模式")
        return template_pairs(events, rng)
    node = pick_llm_node(cfg)
    if node is None:
        print("config.yml 里没有可用端点，退回模板模式")
        return template_pairs(events, rng)
    client = OpenAI(api_key=node["api_key"], base_url=node["base_url"])
    model_name = str(node.get("model") or "deepseek-chat")
    batches = [events[i:i + batch] for i in range(0, len(events), batch)]

    def one(items: list[dict]) -> dict | None:
        text = "\n".join(f"{i}. {e['event']}" for i, e in enumerate(items))
        try:
            resp = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": LLM_PROMPT.format(items=text)}],
                temperature=0.7, max_tokens=400)
            body = re.sub(r"^```(json)?|```$", "",
                          resp.choices[0].message.content.strip(), flags=re.M).strip()
            data = json.loads(body)
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(data, dict) or not data.get("query"):
            return None
        idx = int(data.get("used_index") or 0)
        ev = items[idx] if 0 <= idx < len(items) else items[0]
        return {"query": str(data["query"]).strip(),
                "response": str(data.get("response") or "").strip(), "event": ev}

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for i, row in enumerate(pool.map(one, batches), 1):
            if row and row["response"]:
                rows.append(row)
            if i % 20 == 0:
                print(f"  合成 {i}/{len(batches)} 批，有效 {len(rows)} 条", flush=True)
    return rows or template_pairs(events, rng)


def build_context(pool: list[dict], chosen: dict, rng: random.Random,
                  size: int) -> tuple[str, list[int]]:
    """context = 1 条目标事件 + 若干干扰事件（打散），返回 (文本, 段长)。"""
    others = [e for e in pool if e["eid"] != chosen["eid"]]
    rng.shuffle(others)
    items = [chosen] + others[: max(0, size - 1)]
    rng.shuffle(items)
    lines = [f"- {ev['event']}" for ev in items]
    return "以下是我记住的事情：\n" + "\n".join(lines), [len(x) for x in lines]


# ------------------------------------------------------------------ 主流程
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--abmem", default=DEFAULT_ABMEM)
    ap.add_argument("--userinfo", default=DEFAULT_USERINFO)
    ap.add_argument("--record", default=DEFAULT_RECORD)
    ap.add_argument("--config", default=os.path.join(MODULE_ROOT, "config.yml"))
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--mode", choices=("template", "llm"), default="template")
    ap.add_argument("--limit", type=int, default=2000,
                    help="目标样本数（不足时按事件数自动重复问法）")
    ap.add_argument("--context-events", dest="context_events", type=int, default=24)
    ap.add_argument("--neutral-ratio", dest="neutral_ratio", type=float, default=0.1)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    events: list[dict] = []
    if os.path.isdir(args.abmem):
        for name in sorted(os.listdir(args.abmem)):
            if name.endswith(".json") and not name.startswith("index"):
                batch = load_events(os.path.join(args.abmem, name))
                events.extend(batch)
                print(f"  {name}: {len(batch)} 条记忆")
    if not events:
        print(f"没读到记忆条目（{args.abmem}）")
        return 1
    print(f"记忆条目合计 {len(events)} 条")

    pairs = template_pairs(events, rng)
    if args.mode == "llm":
        import yaml

        cfg = {}
        if os.path.isfile(args.config):
            with open(args.config, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
        pairs = llm_pairs(events, cfg, rng, workers=args.workers)
        print(f"教师模型合成 {len(pairs)} 条问答对")
    else:
        print(f"模板合成 {len(pairs)} 条问答对")

    # 样本不够就换问法重复（同事件不同 id，但 event_id 相同 -> 切分时不会被拆开）
    while len(pairs) < args.limit and pairs:
        extra = []
        for pair in pairs:
            if len(pairs) + len(extra) >= args.limit:
                break
            extra.append(dict(pair))
        if not extra:
            break
        pairs.extend(extra)
    rng.shuffle(pairs)
    pairs = pairs[: args.limit]

    rows: list[dict] = []
    for i, pair in enumerate(pairs):
        context, segments = build_context(events, pair["event"], rng,
                                          args.context_events)
        rows.append({
            "id": f"abmem-{i:06d}",
            "event_id": pair["event"]["eid"],
            "context": context,
            "query": pair["query"],
            "response": pair["response"],
            "segments": segments,
            "source": f"abstract_memory/{args.mode}",
        })

    # 记忆里没有的负样本：抑制"什么都要翻记忆"的倾向
    for i in range(int(len(rows) * args.neutral_ratio)):
        context, _ = build_context(events, rng.choice(events), rng,
                                   args.context_events)
        rows.append({
            "id": f"neutral-{i:06d}",
            "event_id": f"neutral-{i}",
            "context": context,
            "query": rng.choice(NEUTRAL_QUERIES),
            "response": "（换成角色卡风格的真实回复）",
            "segments": [],
            "source": "neutral",
        })

    dialogs = load_records(args.record)
    for i, turns in enumerate(dialogs):
        if len(turns) < 2:
            continue
        speaker, text = turns[-1]
        rows.append({
            "id": f"dialog-{i:06d}",
            "event_id": f"dialog-{i}",
            "context": "\n".join(f"{a}：{b}" for a, b in turns[:-1]),
            "query": "接着上面的话说一句。",
            "response": text,
            "segments": [len(b) for _, b in turns[:-1]],
            "source": "record",
        })
    print(f"对话轮次样本 {len(dialogs)} 段；用户档案 {len(load_userinfo(args.userinfo))} 份")

    rng.shuffle(rows)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    count = write_jsonl(args.out, rows)
    print(f"写出 {count} 条 -> {args.out}")
    print("提醒：neutral / dialog 两类只是骨架，正式训练前把 response 换成真实回复。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
