# -*- coding: utf-8 -*-
"""δ-mem 长对话评测：**英文 + 50 轮 + 中途多次探针**。

和 `dmem_eval.py` 的区别
------------------------
`dmem_eval.py` 是"一问一答"的短测；这个脚本测的是**记忆能不能扛住长对话**：
第 1 轮把事实/约束说出来并写进 δ-mem，然后灌 48 轮无关闲聊，在第 12/25/38/50 轮
插探针，看还记不记得、还守不守得住。

为什么用英文
------------
训练数据 76% 是英文 LoCoMo 对话原文（`sft.jsonl` / `real_lo.jsonl`，context 固定
6000 字符、response mean 33 字符）。中文短断言是分布外，先把语言这一维对齐，
才能判断剩下的问题是不是"注入强度"或"写入量"。

为什么 50 轮
------------
δ-mem 的状态在生成期是冻结的、只在写记忆时更新；对话轮次本身不会污染状态，
但会长距离考验"读"是否稳定（每轮 attention 都要用到状态）。

用法
----
    python dmem_eval_en.py                          # 3 场景 × 2 臂 × 50 轮
    python dmem_eval_en.py --turns 50 --repeats 1
    python dmem_eval_en.py --only 1 --arms with_mem  # 只跑一个臂（调试）
    python dmem_eval_en.py --tag alpha4              # 结果里打标，便于对比
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:18100/meowllm"

# ---------------------------------------------------------------------- 场景
SCENARIOS = [
    {
        "id": 1, "kind": "allergy-constraint", "owner": "000301",
        "plant": ("Quick note before we start: I am severely allergic to peanuts. "
                  "Even a trace of peanut butter or peanut oil sends me to the hospital, "
                  "so never suggest anything containing peanuts for me."),
        "probes": [
            {"q": "I feel like making peanut butter noodles for dinner tonight. Any ideas?",
             "watch": ["allerg", "can't", "cannot", "avoid", "different", "not safe",
                       "instead", "swap"],
             "forbid": ["tablespoons of peanut butter", "peanut butter is a great"]},
        ],
    },
    {
        "id": 2, "kind": "fact-recall", "owner": "000302",
        "plant": ("Let me tell you something about my family: my sister's name is Margot "
                  "and she lives in Lisbon with her two cats."),
        "probes": [
            {"q": "What's my sister's name, and where does she live?",
             "watch": ["Margot"], "forbid": ["don't know", "not sure", "no idea"]},
        ],
    },
    {
        "id": 3, "kind": "taste-preference", "owner": "000303",
        "plant": ("One thing about me: I absolutely hate cilantro, it tastes like soap. "
                  "But I love spicy food, the hotter the better."),
        "probes": [
            {"q": "Suggest something for dinner tonight.",
             "watch": ["spicy", "spice", "hot", "chili", "chilli"],
             "forbid": ["cilantro", "coriander"]},
        ],
    },
]

# 48 条无关闲聊（故意与三个场景无关，也不能泄露答案）；都要求一句话，控制耗时
FILLERS = [
    "Tell me one fun fact about octopuses.", "How do I stay focused while studying?",
    "What's a good name for a small orange cat?", "Explain what a rainbow is in one line.",
    "Give me one tip for sleeping better.", "What's the capital of Norway?",
    "Tell me a short joke about programmers.", "How do plants make food?",
    "What's one benefit of walking every day?", "Name one famous painter.",
    "How deep is the deepest ocean trench?", "What does a barometer measure?",
    "Give me one tip for keeping a desk tidy.", "What is the boiling point of water at sea level?",
    "Tell me one thing about the moon.", "What's a simple breakfast idea?",
    "How do bees communicate?", "Name one country in South America.",
    "What's a good way to learn new vocabulary?", "Explain what gravity does in one line.",
    "Tell me one fact about the pyramids.", "What's the largest desert on Earth?",
    "How long does it take to boil an egg?", "Name one musical instrument.",
    "What's a good stretch for a stiff back?", "Tell me one thing about volcanoes.",
    "What's the difference between a lake and a pond?", "Give me one tip for saving money.",
    "What's a common cause of headaches?", "Name one kind of cloud.",
    "How do you convert Celsius to Fahrenheit?", "Tell me one fact about the sun.",
    "What's a good way to start running?", "Explain what a metaphor is in one line.",
    "Name one animal that lives in the Arctic.", "What's a simple way to reduce plastic use?",
    "How does a refrigerator keep food cold?", "Tell me one thing about honey.",
    "What's a good board game for two people?", "Name one vitamin found in oranges.",
    "How do you fold a fitted sheet?", "What causes thunder?",
    "Tell me one fact about ancient Rome.", "What's a nice way to greet a neighbour?",
    "How many minutes should you brush your teeth?", "Name one thing made of glass.",
    "What's a simple way to water plants while away?", "Give me one tip for a tidy inbox.",
]

# 探针插在哪几轮（1 是 planted 那轮，不算）
PROBE_TURNS = (12, 25, 38, 50)


def post(base: str, path: str, payload: dict, timeout: float = 240.0) -> dict:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(base: str, path: str, timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(base + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat(base: str, history: list[dict], owner: str | None,
         max_tokens: int = 64, context_limit: int = 0) -> dict:
    body = {
        "model": "meowllm-local",
        "messages": history,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "meowllm": {"thinking_level": "off"},
    }
    if owner:
        body["meowllm"]["memory_owner"] = owner
    if context_limit:
        # **这是本实验的关键**：把 prompt 裁剪到这么小，第 1 轮的 plant 会在
        # 十几轮之后被挤出上下文窗口 —— 于是"还记得约束"只能来自 δ-mem。
        # 不设它的话，历史里一直有那句话，no_mem 臂也能答对，测的就不是记忆。
        body["meowllm"]["context_limit"] = int(context_limit)
    t0 = time.time()
    try:
        r = post(base, "/v1/chat/completions", body)
    except Exception as exc:  # noqa: BLE001
        return {"text": "", "error": f"{type(exc).__name__}: {exc}",
                "ms": round((time.time() - t0) * 1000)}
    text = (r["choices"][0]["message"].get("content") or "").strip()
    return {"text": text, "usage": r.get("usage"),
            "ms": round((time.time() - t0) * 1000),
            "ufffd": text.count("\ufffd")}


def judge(text: str, watch, forbid) -> dict:
    low = text.lower()
    hit = [w for w in (watch or []) if w.lower() in low]
    bad = [w for w in (forbid or []) if w.lower() in low]
    return {"hit": hit, "violated": bad,
            "ok": (bool(hit) if watch else True) and not bad}


def build_turns() -> list[dict]:
    """50 轮的骨架：第 1 轮 plant，其余 filler，指定轮次换成探针。"""
    turns = []
    fi = 0
    for n in range(1, 51):
        if n == 1:
            turns.append({"n": n, "role": "plant"})
        elif n in PROBE_TURNS:
            turns.append({"n": n, "role": "probe"})
        else:
            turns.append({"n": n, "role": "filler", "text": FILLERS[fi % len(FILLERS)]})
            fi += 1
    return turns


def run(base: str, turns_wanted: int, arms: tuple[str, ...],
        only: set[int] | None, max_tokens: int,
        context_limit: int = 512) -> dict:
    result = {
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base": base, "turns": turns_wanted, "arms": list(arms),
        "lang": "en", "max_tokens": max_tokens, "temperature": 0.7,
        "context_limit": context_limit,
        "probe_turns": list(PROBE_TURNS), "scenarios": [],
    }
    try:
        result["dmem_status"] = get(base, "/control/dmem/status")
    except Exception:  # noqa: BLE001
        pass

    skeleton = build_turns()[:turns_wanted]

    for sc in SCENARIOS:
        if only and sc["id"] not in only:
            continue
        print(f"\n=== 场景 {sc['id']} {sc['kind']} owner={sc['owner']} ===", flush=True)
        try:
            w = post(base, "/control/dmem/write",
                     {"owner": sc["owner"], "text": sc["plant"], "mode": "replace"})
            print(f"  写入记忆: tokens={w.get('tokens')} chunks={w.get('chunks')} "
                  f"{w.get('seconds')}s", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  写入失败: {exc}", flush=True)
            w = {"ok": False, "error": str(exc)}

        row = {"id": sc["id"], "kind": sc["kind"], "owner": sc["owner"],
               "plant": sc["plant"], "write": w, "arms": {}}

        for arm in arms:
            owner = sc["owner"] if arm.startswith("with") else None
            history: list[dict] = []
            probes = []
            errors = 0
            ufffd = 0
            for t in skeleton:
                if t["role"] == "plant":
                    user_text = sc["plant"]
                elif t["role"] == "probe":
                    user_text = sc["probes"][0]["q"]
                else:
                    user_text = t["text"]
                history.append({"role": "user", "content": user_text})
                r = chat(base, history, owner, max_tokens, context_limit)
                if r.get("error"):
                    errors += 1
                txt = r.get("text", "")
                ufffd += r.get("ufffd", 0)
                history.append({"role": "assistant", "content": txt or "(empty)"})
                if t["role"] == "probe":
                    j = judge(txt, sc["probes"][0].get("watch"),
                              sc["probes"][0].get("forbid"))
                    probes.append({"turn": t["n"], "q": user_text, "text": txt,
                                   "ok": j["ok"], "hit": j["hit"],
                                   "violated": j["violated"],
                                   "ms": r.get("ms"), "ufffd": r.get("ufffd", 0)})
                    flag = "✓" if j["ok"] else "✗"
                    print(f"  [{arm}] turn {t['n']:>2} 探针 {flag} hit={j['hit']} "
                          f"bad={j['violated']} {r.get('ms')}ms", flush=True)
                elif t["n"] % 10 == 0:
                    print(f"  [{arm}] turn {t['n']:>2} …", flush=True)
            row["arms"][arm] = {"probes": probes, "errors": errors,
                                "ufffd_total": ufffd}
        result["scenarios"].append(row)

    try:
        result["dmem_status_after"] = get(base, "/control/dmem/status")
    except Exception:  # noqa: BLE001
        pass
    result["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return result


def summarise(res: dict) -> str:
    lines = []
    for sc in res.get("scenarios", []):
        lines.append(f"场景 {sc['id']} ({sc['kind']})")
        for arm, body in sc["arms"].items():
            ps = body["probes"]
            rate = sum(1 for p in ps if p["ok"])
            curve = "".join("●" if p["ok"] else "○" for p in ps)
            lines.append(f"  {arm:<10} {rate}/{len(ps)}  {curve}  "
                         f"err={body['errors']} ufffd={body['ufffd_total']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("MEOWLLM_BASE", DEFAULT_BASE))
    ap.add_argument("--turns", type=int, default=50)
    ap.add_argument("--max-tokens", type=int, default=64)
    ap.add_argument("--arms", default="with_mem,no_mem")
    ap.add_argument("--only", default="")
    ap.add_argument("--tag", default="", help="结果里打标，便于版本对比")
    ap.add_argument("--context-limit", type=int, default=512,
                    help="每次请求的 prompt 裁剪上限（token）。设小才能让第 1 轮的 plant "
                         "在十几轮后被挤出上下文 —— 否则 no_mem 臂也能从历史里看到答案。"
                         "设 0 = 不裁剪（那样测的就不是记忆了）")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    only = {int(x) for x in args.only.split(",") if x.strip().isdigit()} or None
    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    out = args.out or os.path.join(
        os.environ.get("TEMP") or os.environ.get("TMP") or ".",
        f"dmem_eval_en_{args.tag or 'run'}_{time.strftime('%Y%m%d-%H%M%S')}.json")

    print(f"base={args.base} turns={args.turns} arms={arms} tag={args.tag}")
    res = run(args.base, args.turns, arms, only, args.max_tokens,
              context_limit=args.context_limit)
    res["tag"] = args.tag
    res["summary"] = summarise(res)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    print("\n" + res["summary"])
    print(f"\n结果：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
