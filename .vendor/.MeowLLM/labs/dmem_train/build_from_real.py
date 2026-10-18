# -*- coding: utf-8 -*-
"""从**真人公开数据**构造 δ-mem 的 (context, query, response) 样本。

为什么不能直接喂
----------------
真人数据是"连续多会话聊天"，没有"答案只在历史里"的标注。δ-mem 的训练约定是
context 写进状态、**不进** backbone 输入（论文 §3.6），所以必须构造：

    前 k-1 个 session  -> context（写进状态）
    第 k 个 session 的 user 话  -> query
    第 k 个 session 的 assistant 话 -> response

然后过三道闸（缺一道这批数据就废）：
    ① 实体闸：response 里的实体/数字必须在 context 出现、且不在 query 出现
    ② 判官闸（--filter-judge）：让 LLM 判"删掉 context 还能答吗"，能则丢
    ③ NLL 闸：训练后用 no-context NLL − with-state NLL ≤ 0 的样本剔除再训

支持的数据集
------------
    --dataset sessions   通用格式（自己转好的 JSONL，最推荐）
    --dataset locomo     snap-research/locomo（英文，超长多会话）
    --dataset perltqa    Elvin-Yiming-Du/PerLTQA（中文，个人长期记忆）
    --dataset msc        ParlAI MSC 导出后的 JSON（英文，真人多会话）

用法
----
    # 先探一下格式（不写文件，只打印结构，方便你按需改）
    python build_from_real.py --dataset locomo --input data/raw/locomo --probe

    # 正式构造
    python build_from_real.py --dataset locomo --input data/raw/locomo \
        --out data/real.jsonl --filter-judge
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from dataset import write_jsonl  # noqa: E402


# ------------------------------------------------------------------ 实体抽取
_NUM = re.compile(r"\d+(?:\.\d+)?")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]{2,}")
_QUOTED = re.compile(r"[「『\"“']([^」』\"”']{1,24})[」』\"”']")
#: 中文里"承载信息"的词：名词性短语很难切，这里用"人名/称呼/专名"的粗线索
_CN_HINT = re.compile(r"(?:叫|是|在|去|买了|吃了|养了|喜欢|讨厌|住在|做了)"
                      r"([\u4e00-\u9fa5]{2,6})")
_STOP = set("的了是我你他她它们这那有不没在和就都也很还再又去来到说要做看想会能个"
            "吗呢吧啊哦嗯好对呀嘛哈已经因为所以但是然后就是什么怎么为什么")


def entities(text: str) -> set[str]:
    """粗抽"实体"：数字、拉丁词、引号内容、中文提示词后的 2~6 字片段。"""
    out: set[str] = set()
    for pat in (_NUM, _LATIN, _QUOTED, _CN_HINT):
        for m in pat.finditer(text or ""):
            token = (m.group(1) if m.groups() else m.group(0)).strip()
            if len(token) >= 2 and token not in _STOP:
                out.add(token.lower())
    return out


def passes_entity_gate(context: str, query: str, response: str) -> bool:
    """① 实体闸：答案的实体来自 context，而不是来自 query 自身。"""
    if len(response or "") < 4:
        return False
    in_answer = entities(response)
    if not in_answer:
        return False
    in_context = entities(context)
    in_query = entities(query)
    grounded = in_answer & in_context
    if not grounded:
        return False
    # 全部实体都只来自 query -> 不看记忆也能答，丢掉
    return bool(grounded - in_query)


# ------------------------------------------------------------------ 会话工具
def session_text(sessions: list[list[dict]], limit_sessions: int | None = None) -> str:
    """把多会话拼成"记忆流水"（context）。"""
    rows: list[str] = []
    picked = sessions if limit_sessions is None else sessions[-limit_sessions:]
    for i, session in enumerate(picked, 1):
        rows.append(f"【第 {i} 次聊天】")
        for turn in session:
            speaker = str(turn.get("speaker") or turn.get("role") or "?").strip()
            text = str(turn.get("text") or turn.get("content") or "").strip()
            if text:
                rows.append(f"{speaker}：{text}")
    return "\n".join(rows)


def pair_from_sessions(sessions: list[list[dict]], max_context_sessions: int = 3
                       ) -> tuple[str, str, str]:
    """取最后一个 session 的最后一轮做 (query, response)，前面的做 context。"""
    if len(sessions) < 2:
        return "", "", ""
    history = sessions[:-1]
    last = sessions[-1]
    if len(last) < 2:
        return "", "", ""
    # 从后往前找一对"user -> assistant"
    for i in range(len(last) - 1, 0, -1):
        speaker = str(last[i].get("speaker") or last[i].get("role") or "").lower()
        if speaker in ("user", "human", "主人") or "user" in speaker:
            return (session_text(history, max_context_sessions),
                    str(last[i].get("text") or last[i].get("content") or "").strip(),
                    str(last[i + 1].get("text") or last[i + 1].get("content") or "").strip()
                    if i + 1 < len(last) else "")
    # 退而求其次：用最后两轮
    a, b = last[-2], last[-1]
    return (session_text(history, max_context_sessions),
            str(a.get("text") or a.get("content") or "").strip(),
            str(b.get("text") or b.get("content") or "").strip())


# ------------------------------------------------------------------ 读取器
def read_sessions_jsonl(path: str) -> list[dict]:
    """通用格式：一行一段多会话对话。

    {"id":"x","sessions":[[{"speaker":"user","text":"..."},...], [...]]}
    """
    rows = []
    # utf-8-sig：Windows 上造出来的 json 常带 BOM，用 utf-8 会直接解析失败
    with open(path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def read_locomo(path: str) -> list[dict]:
    """LoCoMo：一个/多个 json，里面有 conversation（sessions）与 qa。"""
    files = ([path] if os.path.isfile(path)
             else sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)))
    out = []
    for file in files:
        try:
            data = json.load(open(file, encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            conv = item.get("conversation") or item.get("conversations") or {}
            sessions = _locomo_sessions(conv)
            if len(sessions) < 2:
                continue
            qa = item.get("qa") or item.get("QAs") or []
            out.append({"id": item.get("sample_id") or item.get("id") or
                              os.path.basename(file), "sessions": sessions, "qa": qa})
    return out


def _locomo_sessions(conv) -> list[list[dict]]:
    """LoCoMo 的 conversation 形如 {session_1: [{speaker,text}...], ...} 或 dict 列表。"""
    sessions: list[list[dict]] = []
    if isinstance(conv, dict):
        keys = [k for k in conv if str(k).startswith("session")]
        keys.sort(key=lambda k: int(re.sub(r"\D", "", str(k)) or 0))
        for key in keys:
            turns = conv.get(key)
            if isinstance(turns, list):
                sessions.append([_turn(t) for t in turns if _turn(t)])
    elif isinstance(conv, list):
        for block in conv:
            if isinstance(block, list):
                sessions.append([_turn(t) for t in block if _turn(t)])
            elif isinstance(block, dict) and isinstance(block.get("turns"), list):
                sessions.append([_turn(t) for t in block["turns"] if _turn(t)])
    return [s for s in sessions if s]


def _turn(t) -> dict:
    if not isinstance(t, dict):
        return {}
    return {"speaker": t.get("speaker") or t.get("role") or "?",
            "text": t.get("text") or t.get("content") or ""}


def read_perltqa(path: str) -> list[dict]:
    """PerLTQA：`perltmem*.json`（记忆）+ `perltqa*.json`（问答），按 id 合并。

    实测结构（Dataset/zh/）：
        perltmem.json: [{profile, profile_description, social_relationship, events, dialogues}, ...]
        perltqa.json : 带 question/answer 的问答
    早期实现只读 perltmem，于是"有记忆没问答"，一条样本都产不出来。
    """
    files = ([path] if os.path.isfile(path)
             else sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)))
    mem_books: dict[str, dict] = {}
    qa_books: dict[str, list] = {}

    def _key(item: dict, fallback: str) -> str:
        return str(item.get("id") or item.get("pid") or item.get("name")
                   or item.get("uid") or fallback)

    for file in files:
        try:
            data = json.load(open(file, encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            continue
        items = data if isinstance(data, list) else list(data.values()) \
            if isinstance(data, dict) else []
        base = os.path.basename(file).lower()
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            key = _key(item, f"{base}-{i}")
            has_qa = any(k in item for k in ("qa", "QAs", "questions"))
            if has_qa:
                qa_books.setdefault(key, []).extend(
                    item.get("qa") or item.get("QAs") or item.get("questions") or [])
            # 记忆：profile / memories / events / dialogues 都收
            texts: list[str] = []
            for field_name in ("memory", "memories", "profile", "events", "dialogues"):
                value = item.get(field_name)
                if isinstance(value, dict):
                    value = [f"{k}：{v}" for k, v in value.items()]
                if isinstance(value, str):
                    value = [value]
                for entry in (value if isinstance(value, list) else []):
                    if isinstance(entry, str):
                        texts.append(entry)
                    elif isinstance(entry, dict):
                        texts.append(str(entry.get("text") or entry.get("content")
                                         or entry.get("summary") or entry.get("event")
                                         or ""))
            texts = [t.strip() for t in texts if t and t.strip()]
            if texts:
                book = mem_books.setdefault(key, {"texts": [], "qa": []})
                book["texts"].extend(texts)
            if has_qa:
                mem_books.setdefault(key, {"texts": [], "qa": []})["qa"].extend(
                    item.get("qa") or item.get("QAs") or item.get("questions") or [])

    # 两边的键可能不完全对齐（一个按 pid、一个按 name）：键不一致时做"全局配对兜底"
    out: list[dict] = []
    all_qa: list = []
    for key, book in mem_books.items():
        if book.get("qa"):
            all_qa.extend(book["qa"])
        if not book["texts"]:
            continue
        out.append({"id": key,
                    "context": "\n".join(f"- {t}" for t in book["texts"][:80]),
                    "qa": (book.get("qa") or qa_books.get(key) or [])})
    if not any(item["qa"] for item in out) and all_qa:
        # 兜底：记忆和问答分属两本书时，全部问答挂到最长的记忆上
        longest = max(out, key=lambda x: len(x["context"]), default=None)
        if longest:
            longest["qa"] = all_qa
            print(f"  [perltqa] 记忆与问答键不一致，已把 {len(all_qa)} 条问答"
                  f"挂到最长记忆（{longest['id']}）上")
    return out


def _qa_pairs(qa) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if not isinstance(qa, list):
        return pairs
    for item in qa:
        if not isinstance(item, dict):
            continue
        q = item.get("question") or item.get("query") or item.get("q")
        a = item.get("answer") or item.get("response") or item.get("a")
        if isinstance(a, list):
            a = a[0] if a else ""
        if isinstance(q, str) and isinstance(a, str) and q.strip() and a.strip():
            pairs.append((q.strip(), a.strip()))
    return pairs


# ------------------------------------------------------------------ 判官闸
JUDGE = """下面是一条"记忆"和一条"提问"。请判断：如果**完全不看**这段记忆，
仅凭常识和提问本身，能否给出答案？
只回答一个词：能 / 不能

记忆：
{context}

提问：{query}

答案：{response}"""


def make_judge(config_path: str, workers: int):
    """② 判官闸：用 config.yml 里现成的端点。拿不到就返回 None（跳过该闸）。"""
    try:
        import yaml
        from openai import OpenAI

        cfg = yaml.safe_load(open(config_path, encoding="utf-8-sig")) or {}
        node = None
        for item in (cfg.get("llm") or {}).values():
            if isinstance(item, dict) and item.get("api_key") and \
                    "deepseek" in str(item.get("base_url")):
                node = item
                break
        if not node:
            return None
        client = OpenAI(api_key=node["api_key"], base_url=node["base_url"])
        model_name = str(node.get("model") or "deepseek-chat")
    except Exception as exc:  # noqa: BLE001
        print(f"  判官不可用（{exc}），跳过判官闸")
        return None

    def judge(context: str, query: str, response: str) -> bool | None:
        try:
            resp = client.chat.completions.create(
                model=model_name, temperature=0.0, max_tokens=4,
                messages=[{"role": "user", "content": JUDGE.format(
                    context=context[-3000:], query=query, response=response)}])
            text = (resp.choices[0].message.content or "").strip()
            if "不能" in text:
                return True          # 必须看记忆 -> 保留
            if "能" in text:
                return False
            return None
        except Exception:  # noqa: BLE001
            return None

    return judge


# ------------------------------------------------------------------ 主流程
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=("sessions", "locomo", "perltqa", "msc"),
                    default="sessions")
    ap.add_argument("--input", required=True, help="文件或目录")
    ap.add_argument("--out", default=os.path.join(HERE, "data", "real.jsonl"))
    ap.add_argument("--config", default=os.path.join(MODULE_ROOT, "config.yml"))
    ap.add_argument("--max-context-sessions", dest="max_ctx", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="0=不限")
    ap.add_argument("--filter-judge", dest="filter_judge", action="store_true")
    ap.add_argument("--judge-sample", dest="judge_sample", type=float, default=1.0,
                    help="判官只抽这么比例（省钱），过闸的样本按比例放大权重由你决定")
    ap.add_argument("--probe", action="store_true", help="只打印检测到的结构")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    # ---- 读 ----
    if args.dataset == "sessions":
        rows = read_sessions_jsonl(args.input)
    elif args.dataset == "locomo":
        rows = read_locomo(args.input)
    elif args.dataset == "perltqa":
        rows = read_perltqa(args.input)
    else:                      # msc：按通用 sessions 处理，ParlAI 导出后自己转一下
        rows = read_sessions_jsonl(args.input)
    print(f"[1] {args.dataset}: 读到 {len(rows)} 条原始记录")
    if not rows:
        print("    没读到数据。先确认 --input 路径，或加 --probe 看结构。")
        return 1

    if args.probe:
        sample = rows[0]
        print("[probe] 顶层键:", list(sample.keys()))
        sessions = sample.get("sessions")
        if sessions:
            print(f"        sessions={len(sessions)}，第一段轮数={len(sessions[0])}")
            print("        首轮:", json.dumps(sessions[0][:2], ensure_ascii=False)[:200])
        if sample.get("qa"):
            print("        qa 样例:", json.dumps(_qa_pairs(sample["qa"])[:2],
                                              ensure_ascii=False)[:200])
        if sample.get("context"):
            print("        context 长度:", len(sample["context"]))
        return 0

    judge = make_judge(args.config, 1) if args.filter_judge else None
    judge_calls = 0

    # ---- 构造 + 过闸 ----
    out: list[dict] = []
    stat = {"pairs": 0, "entity_gate": 0, "judge_gate": 0, "kept": 0}
    for row in rows:
        # 路线 A：有 qa（LoCoMo/PerLTQA）——直接用问答，context 是记忆流水
        pairs = _qa_pairs(row.get("qa")) if row.get("qa") else []
        if pairs:
            context = row.get("context") or session_text(row.get("sessions") or [])
            if not context:
                continue
            for query, response in pairs:
                stat["pairs"] += 1
                if not passes_entity_gate(context, query, response):
                    stat["entity_gate"] += 1
                    continue
                if judge and (args.judge_sample >= 1.0 or
                              rng.random() < args.judge_sample):
                    judge_calls += 1
                    verdict = judge(context, query, response)
                    if verdict is False:
                        stat["judge_gate"] += 1
                        continue
                eid = hashlib.sha1(f"{row.get('id')}|{query}".encode()).hexdigest()[:12]
                out.append({"id": f"real-{len(out):06d}", "event_id": eid,
                            "context": context, "query": query,
                            "response": response, "segments": [],
                            "source": f"real/{args.dataset}"})
                stat["kept"] += 1
            continue
        # 路线 B：只有 sessions（MSC/通用）——切最后一段的最后一轮
        sessions = row.get("sessions") or []
        context, query, response = pair_from_sessions(sessions, args.max_ctx)
        if not (context and query and response):
            continue
        stat["pairs"] += 1
        if not passes_entity_gate(context, query, response):
            stat["entity_gate"] += 1
            continue
        if judge and (args.judge_sample >= 1.0 or rng.random() < args.judge_sample):
            judge_calls += 1
            verdict = judge(context, query, response)
            if verdict is False:
                stat["judge_gate"] += 1
                continue
        eid = hashlib.sha1(f"{row.get('id')}|{query}".encode()).hexdigest()[:12]
        out.append({"id": f"real-{len(out):06d}", "event_id": eid,
                    "context": context, "query": query, "response": response,
                    "segments": [], "source": f"real/{args.dataset}"})
        stat["kept"] += 1
        if args.limit and len(out) >= args.limit:
            break

    print(f"[2] 候选问答对 {stat['pairs']}；实体闸刷掉 {stat['entity_gate']}；"
          f"判官闸刷掉 {stat['judge_gate']}（调用 {judge_calls} 次）")
    print(f"[3] 保留 {len(out)} 条（通过率 "
          f"{stat['kept'] / max(1, stat['pairs']) * 100:.1f}%）")
    if not out:
        print("    全被刷掉了。检查：response 是不是太短/没有实体；"
              "或关掉 --filter-judge 先看看原始分布。")
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    write_jsonl(args.out, out)
    print(f"[4] 写出 -> {args.out}")
    print("    下一步：python mix.py --real %s --synth data/synth.jsonl "
          "--out data/sft.jsonl" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
