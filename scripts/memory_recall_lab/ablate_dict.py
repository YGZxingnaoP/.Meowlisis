# -*- coding: utf-8 -*-
"""单点消融：用户词典 vs 字二元，看哪个修「分词漏召」更干净。

两者都在解决同一个问题（「英语六级考试」切不出「六级」）：
  用户词典  在线索引前把 tag 词表灌进 jieba —— 不改检索逻辑，只改分词
  字二元    不改分词，靠二元组兜底 —— 但单字二元命中即开闸，负例会被灌满
"""
from __future__ import annotations

import io
import os
import sys
from dataclasses import replace

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lab_algo import RECOMMENDED as BASE, Cfg, hybrid_recall  # noqa: E402
from lab_eval import (  # noqa: E402
    TOP_K, build_ctx, composite, evaluate, load_goldset,
)


def run(ctx, goldset, cfg: Cfg, label: str) -> tuple:
    m = evaluate(ctx, lambda c, q: hybrid_recall(c, q, cfg), goldset)
    return (composite(m), label, m)


def main() -> None:
    goldset = load_goldset()

    # 注意：jieba 是进程级单例，add_word 会永久生效。
    # 所以必须「先测无词典、再测有词典」，否则两次都会带上用户词典，测不出差别。
    ctx_plain = build_ctx(use_userdict=False)
    rows_plain = [
        run(ctx_plain, goldset, BASE, "无词典 · 词+tag"),
        run(ctx_plain, goldset, replace(BASE, use_bigram=True), "无词典 · 加字二元"),
    ]
    ctx_dict = build_ctx(use_userdict=True)
    rows_dict = [
        run(ctx_dict, goldset, BASE, "用户词典(全) · 词+tag"),
        run(ctx_dict, goldset, replace(BASE, use_bigram=True), "用户词典(全) · 加字二元"),
    ]
    ctx_short = build_ctx(use_userdict=True, userdict_max_len=3)
    rows_short = [
        run(ctx_short, goldset, BASE, "用户词典(≤3字) · 词+tag"),
        run(ctx_short, goldset, replace(BASE, use_bigram=True), "用户词典(≤3字) · 加字二元"),
    ]
    rows = sorted(rows_plain + rows_dict + rows_short, key=lambda x: -x[0])

    cols = ["综合", "F1", "recall", "prec", "mrr", "漏答", "噪声", "净召回", "均条", "字符", "ms"]
    w = max(len(r[1]) for r in rows) + 2
    print(f"{'配置':<{w}}" + "".join(f"{c:>9}" for c in cols))
    print("-" * (w + 9 * len(cols)))
    for score, label, m in rows:
        p, r = m["prec_rel"], m["recall_must"]
        f1 = (2 * p * r / (p + r)) if (p + r) else 0.0
        vals = [f"{score:.3f}", f"{f1:.3f}", f"{r:.3f}", f"{p:.3f}", f"{m['mrr']:.3f}",
                f"{int(m['empty_pos'])}", f"{m['neg_noise']:.2f}", f"{m['neg_zero']:.2f}",
                f"{m['avg_n']:.1f}", f"{m['avg_chars']}", f"{m['ms']:.1f}"]
        print(f"{label:<{w}}" + "".join(f"{v:>9}" for v in vals))

    print(f"\n用户词典收录词条：{len(ctx_dict.tok.userdict_terms)} 条")
    print("样例：", "、".join(ctx_dict.tok.userdict_terms[:24]))


if __name__ == "__main__":
    main()
