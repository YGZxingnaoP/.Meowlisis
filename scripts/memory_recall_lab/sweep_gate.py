# -*- coding: utf-8 -*-
"""相关性闸门扫描：不设条数上限，只看「排除多离谱」这一条线怎么定。

对照的是用户的要求：条数不要上限，只在相关性低得离谱时排除。
所以这里扫 gate_ratio（低于「本批最高分 × 该比例」就丢弃），并报告实际注入条数的均值/最大值。
"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, WORKSPACE)

from lab_eval import TOP_K, composite, load_goldset, render_chars  # noqa: E402
from lab_core import load_records  # noqa: E402

os.chdir(WORKSPACE)

from func.catbrain.AbstractMem.process.recall_index import MeowRecallIndex  # noqa: E402


class JiebaSeg:
    def segment(self, text):
        import jieba
        return [w for w in jieba.cut(str(text or "")) if len(w.strip()) > 1]


class Ctx:
    def __init__(self, docs):
        self.docs = docs


def measure(index, goldset, ctx, ratio, k=None):
    recall, prec, mrr = [], [], []
    empty_pos = 0
    neg_noise, neg_zero = [], 0
    counts, chars = [], []
    worst = []
    for item in goldset:
        months = index.retro_months(item["text"])
        full = index.recall(item["text"], months, ratio)
        ids = full if k is None else full[:k]
        counts.append(len(ids))
        chars.append(render_chars(ctx, ids))
        worst.append((len(ids), item["id"], item["text"]))
        if item["kind"] == "pos":
            must = set(item.get("must") or [])
            ok = set(item.get("ok") or [])
            if not ids:
                empty_pos += 1
                recall.append(0.0)
                mrr.append(0.0)
                continue
            recall.append(len(set(ids) & must) / len(must) if must else 0.0)
            prec.append(len(set(ids) & (must | ok)) / len(ids))
            rank = next((i + 1 for i, d in enumerate(ids) if d in must), None)
            mrr.append(1.0 / rank if rank else 0.0)
        else:
            neg_noise.append(len(ids))
            if not ids:
                neg_zero += 1

    def avg(xs):
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    neg_count = len(neg_noise) or 1
    worst.sort(reverse=True)
    return {
        "recall_must": avg(recall),
        "prec_rel": avg(prec),
        "mrr": avg(mrr),
        "empty_pos": float(empty_pos),
        "neg_noise": round(sum(neg_noise) / neg_count, 2),
        "neg_zero": round(neg_zero / neg_count, 3),
        "avg_n": round(sum(counts) / len(counts), 2),
        "max_n": max(counts) if counts else 0,
        "avg_chars": int(sum(chars) / max(1, len(chars))),
        "worst": worst[:2],
    }


def main() -> None:
    import jieba
    jieba.initialize()
    docs = load_records()
    ctx = Ctx(docs)
    raw = []
    for path in sorted(glob.glob(os.path.join(WORKSPACE, "character", "abstract_memory", "meow-*.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            raw += [x for x in json.load(fh) if isinstance(x, dict)]
    index = MeowRecallIndex(raw, JiebaSeg())
    goldset = load_goldset()

    print("不设条数上限，只调相关性闸门（gate_ratio）\n")
    print(f"{'闸门':<8}{'均条':>7}{'最多':>7}{'密度':>8}{'recall':>8}{'prec':>7}"
          f"{'噪声':>7}{'字符':>7}{'综合':>8}")
    print("-" * 72)
    for ratio in (0.02, 0.30, 0.40, 0.45, 0.50, 0.55, 0.60):
        m = measure(index, goldset, ctx, ratio)
        density = m["avg_n"] / max(1, m["max_n"])
        print(f"{ratio:<8.2f}{m['avg_n']:>7.1f}{m['max_n']:>7}{density:>8.0%}"
              f"{m['recall_must']:>8.3f}{m['prec_rel']:>7.3f}{m['neg_noise']:>7.2f}"
              f"{m['avg_chars']:>7}{composite(m):>8.3f}")

    print("\n各闸门下的「注入最多」的两条查询：")
    for ratio in (0.0, 0.10, 0.30, 0.60):
        m = measure(index, goldset, ctx, ratio)
        worst = "；".join(f"{n}条 {qid}「{text}」" for n, qid, text in m["worst"])
        print(f"  {ratio:.2f}: {worst}")


if __name__ == "__main__":
    main()
