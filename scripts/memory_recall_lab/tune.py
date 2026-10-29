# -*- coding: utf-8 -*-
"""在网格最优点附近做定向对照，输出「召回—精确—噪声—体积」的权衡曲线。

网格是贪心的，会漏掉「参数间需要同时改变」才生效的组合，这一层用来补。
"""
from __future__ import annotations

import io
import json
import os
import sys
from dataclasses import replace

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lab_algo import RECOMMENDED as BASE, hybrid_recall  # noqa: E402
from lab_eval import (  # noqa: E402
    TOP_K,
    build_ctx,
    composite,
    evaluate,
    load_goldset,
)

CANDIDATES = [
    ("① 推荐配置（词+tag+实体+时间）", {}),
    ("② +字二元通道", {"use_bigram": True, "bigram_min_hits": 2}),
    ("③ 预算收紧 2+4", {"core_n": 2, "supp_n": 4}),
    ("④ 预算 2+6", {"core_n": 2, "supp_n": 6}),
    ("⑤ 关 tag 通道", {"use_tag": False}),
    ("⑥ 关实体通道", {"use_entity": False}),
    ("⑦ 关时间通道", {"use_time": False}),
    ("⑧ 只留词+tag（关实体+时间）", {"use_entity": False, "use_time": False}),
    ("⑨ 闸门改 P75", {"gate_mode": "p75", "gate_value": 0.0}),
    ("⑩ 闸门 0.6", {"gate_value": 0.6}),
    ("⑪ 闸门 0.4", {"gate_value": 0.4}),
    ("⑫ 不过滤高频词", {"max_df_ratio": 0.0}),
    ("⑬ tag 门槛 2.5", {"tag_gate": 2.5}),
    ("⑭ 字二元 + 预算2+6", {"use_bigram": True, "core_n": 2, "supp_n": 6}),
    ("⑮ 字二元 + 预算3+6", {"use_bigram": True, "core_n": 3, "supp_n": 6}),
    ("⑯ 字二元 + 预算2+8", {"use_bigram": True, "core_n": 2, "supp_n": 8}),
]


def main() -> None:
    ctx = build_ctx()
    goldset = load_goldset()
    rows = []
    for name, patch in CANDIDATES:
        cfg = replace(BASE, **patch)
        m = evaluate(ctx, lambda c, q, _c=cfg: hybrid_recall(c, q, _c), goldset)
        rows.append((composite(m), name, m))

    rows.sort(key=lambda x: -x[0])
    cols = ["综合", "F1", "recall", "prec", "mrr", "漏答", "噪声", "净召回", "均条", "字符", "ms"]
    w = max(len(r[1]) for r in rows) + 2
    print(f"{'配置':<{w}}" + "".join(f"{c:>9}" for c in cols))
    print("-" * (w + 9 * len(cols)))
    for score, name, m in rows:
        p, r = m["prec_rel"], m["recall_must"]
        f1 = (2 * p * r / (p + r)) if (p + r) else 0.0
        vals = [f"{score:.3f}", f"{f1:.3f}", f"{r:.3f}", f"{p:.3f}", f"{m['mrr']:.3f}",
                f"{int(m['empty_pos'])}", f"{m['neg_noise']:.2f}", f"{m['neg_zero']:.2f}",
                f"{m['avg_n']:.1f}", f"{m['avg_chars']}", f"{m['ms']:.1f}"]
        print(f"{name:<{w}}" + "".join(f"{v:>9}" for v in vals))

    best = max(rows, key=lambda x: x[0])
    print(f"\n最优：{best[1]}")
    with open(os.path.join(HERE, "lab_tradeoff.json"), "w", encoding="utf-8") as fh:
        json.dump([{"name": n, "score": round(s, 4),
                    **{k: v for k, v in m.items() if k != "_per_query"}}
                   for s, n, m in rows], fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
