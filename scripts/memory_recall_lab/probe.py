# -*- coding: utf-8 -*-
"""标注辅助：对每条查询，列出「包含任一查询词」的候选条目，供人工挑选 gold。

刻意不使用 BM25 排序（避免用被测算法给被测算法出题），
只按「命中的查询词数 ↓、命中词的 IDF 之和 ↓」排序，并对每条只显示前 8 条。
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lab_core import (  # noqa: E402
    EntityIndex,
    InvertedIndex,
    MonthIndex,
    Tokenizer,
    load_records,
    prime_jieba,
)
from lab_algo import Ctx  # noqa: E402


def main() -> None:
    prime_jieba()
    docs = load_records()
    tok = Tokenizer(docs)
    ctx = Ctx(
        docs=docs,
        tok=tok,
        index=InvertedIndex.build(docs, tok),
        entity=EntityIndex.build(docs),
        month=MonthIndex.build(docs),
    )
    qfile = os.path.join(HERE, "goldset.json")
    with open(qfile, "r", encoding="utf-8") as fh:
        qs = json.load(fh)["queries"]

    print(f"语料 {len(docs)} 条\n")
    for q in qs:
        if q["kind"] == "neg":
            continue
        terms = ctx.tok.query_terms(q["text"])
        live = [t for t in terms if ctx.index.df.get(t)]
        print(f"=== {q['id']} [{q['kind']}] {q['text']}")
        print(f"    词: {terms}")
        print(f"    有命中: {[(t, ctx.index.df[t]) for t in live]}")
        cands = []
        for d in ctx.docs:
            hit = [t for t in live if t in d.event or any(t in tag for tag in d.tags)]
            if not hit:
                continue
            idf_sum = sum(ctx.index.idf(t) for t in hit)
            cands.append((len(hit), idf_sum, d))
        cands.sort(key=lambda x: (-x[0], -x[1], x[2].time))
        if not cands:
            print("    (无候选)")
        for rank, (n, idf, d) in enumerate(cands[:8], 1):
            print(f"    {rank}. {d.doc_id}  n={n} idf={idf:.1f} [{d.time[:10]}] "
                  f"{'/'.join(d.tags[:3])} | {d.event[:56]}")
        if len(cands) > 8:
            print(f"    … 另有 {len(cands) - 8} 条")
        print()


if __name__ == "__main__":
    main()
