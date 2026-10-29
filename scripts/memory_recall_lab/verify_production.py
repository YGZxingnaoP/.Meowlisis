# -*- coding: utf-8 -*-
"""用评测集校验主程序实现（func/catbrain/AbstractMem/process/recall_index.py）。

实验室里的算法是「参考实现」，真正上线的是主程序那份。
这个脚本直接 import 主程序的 MeowRecallIndex，跑同一套 goldset，
确认两者的 recall / prec / 噪声一致——否则说明落地时改坏了。

用法：python verify_production.py
"""
from __future__ import annotations

import io
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
from func.catbrain.catbrain import MeowCatBrainConfig  # noqa: E402

_CFG = MeowCatBrainConfig()
GATE = float(_CFG.recall_gate_ratio)
CAP = int(_CFG.summary_top_limit or 0)


class JiebaSeg:
    def segment(self, text):
        import jieba
        return [w for w in jieba.cut(str(text or "")) if len(w.strip()) > 1]


class Ctx:
    def __init__(self, docs):
        self.docs = docs


def main() -> None:
    import jieba
    jieba.initialize()
    docs = load_records()
    raw = []
    import glob
    import json
    for path in sorted(glob.glob(os.path.join(WORKSPACE, "character", "abstract_memory", "meow-*.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            raw += [x for x in json.load(fh) if isinstance(x, dict)]

    index = MeowRecallIndex(raw, JiebaSeg())
    goldset = load_goldset()
    ctx = Ctx(docs)

    def run(tag, cut):
        recall, prec, mrr = [], [], []
        empty_pos = 0
        neg_noise, neg_zero = [], 0
        all_n, all_chars, times = [], [], []
        import time as _t

        for item in goldset:
            t0 = _t.perf_counter()
            months = index.retro_months(item["text"])
            ids = index.recall(item["text"], months, GATE)
            if CAP > 0:
                ids = ids[:CAP]
            times.append((_t.perf_counter() - t0) * 1000)
            if cut:
                ids = ids[:cut]
            all_n.append(len(ids))
            all_chars.append(render_chars(ctx, ids))
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
        m = {
            "recall_must": avg(recall),
            "prec_rel": avg(prec),
            "mrr": avg(mrr),
            "empty_pos": float(empty_pos),
            "neg_noise": round(sum(neg_noise) / neg_count, 2),
            "neg_zero": round(neg_zero / neg_count, 3),
            "avg_n": round(sum(all_n) / len(all_n), 2),
            "max_n": max(all_n) if all_n else 0,
            "avg_chars": int(sum(all_chars) / max(1, len(all_chars))),
            "ms": round(sum(times) / max(1, len(times)), 2),
        }
        print(f"\n[{tag}]")
        print(f"  recall_must {m['recall_must']:.3f}   prec_rel {m['prec_rel']:.3f}   "
              f"mrr {m['mrr']:.3f}   漏答 {int(m['empty_pos'])}")
        print(f"  负例噪声 {m['neg_noise']:.2f}   净召回 {m['neg_zero']:.2f}   "
              f"均条 {m['avg_n']:.1f}   最多 {m['max_n']}")
        print(f"  字符 {m['avg_chars']}   ms {m['ms']:.2f}")
        return m

    run("全量注入（不设条数上限，仅 summary_top_limit 兜底）", None)
    run(f"同口径 top-{TOP_K}（与旧方案可比）", TOP_K)
    print("\n旧方案参考：recall 0.722 / prec 0.298 / 噪声 8.00 / 均条 30.0 / 字符 875 / 10.5ms")


if __name__ == "__main__":
    main()
