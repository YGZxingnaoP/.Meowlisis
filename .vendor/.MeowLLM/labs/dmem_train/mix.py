# -*- coding: utf-8 -*-
"""把真人样本与 AI 合成样本按比例混合成最终训练集。

默认真人优先（--real-ratio 0.85）。去重按 `event_id`，并做规模裁剪：
不会因为合成数据多就把真人数据挤掉。

    python mix.py --real data/real.jsonl --synth data/synth.jsonl \
                  --out data/sft.jsonl --real-ratio 0.85
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from dataset import read_jsonl, write_jsonl  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", default=os.path.join(HERE, "data", "real.jsonl"))
    ap.add_argument("--synth", default=os.path.join(HERE, "data", "synth.jsonl"))
    ap.add_argument("--out", default=os.path.join(HERE, "data", "sft.jsonl"))
    ap.add_argument("--real-ratio", dest="real_ratio", type=float, default=0.85)
    ap.add_argument("--total", type=int, default=0, help="0=全部")
    ap.add_argument("--neutral", type=int, default=0, help="额外补多少条负样本")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    real = read_jsonl(args.real) if os.path.isfile(args.real) else []
    synth = read_jsonl(args.synth) if os.path.isfile(args.synth) else []
    print(f"真人 {len(real)} 条 / 合成 {len(synth)} 条")
    if not real and not synth:
        print("两边都空，先跑 build_from_real.py 和 build_data.py")
        return 1

    if args.total and args.total > 0:
        allow_real = int(args.total * args.real_ratio)
        allow_synth = args.total - allow_real
        rng.shuffle(real)
        rng.shuffle(synth)
        real = real[:min(len(real), allow_real)]
        synth = synth[:min(len(synth), allow_synth)]
        # 真人不够就让合成补位（反之亦然）
        if len(real) < allow_real:
            synth = synth[:min(len(synth), args.total - len(real))]

    merged: list[dict] = []
    seen: set[str] = set()
    for row in real + synth:
        key = str(row.get("event_id") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(row)

    if args.neutral:
        pool = list(merged)
        for i in range(args.neutral):
            if not pool:
                break
            base = rng.choice(pool)
            merged.append({**base, "id": f"neutral-mix-{i:05d}",
                           "event_id": f"neutral-mix-{i}",
                           "query": "今天心情怎么样？",
                           "response": "（换成角色卡风格的真实回复）",
                           "source": "neutral"})

    rng.shuffle(merged)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    count = write_jsonl(args.out, merged)
    real_n = sum(1 for r in merged if str(r.get("source", "")).startswith("real"))
    print(f"合并去重后 {count} 条（真人 {real_n} = {real_n / max(1, count) * 100:.1f}%）"
          f" -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
