# -*- coding: utf-8 -*-
"""逐查询诊断：漏的是「排序没进」「闸门挡了」还是「预算截了」。

用法：
  python diagnose.py                # 用推荐配置跑 hybrid4
  python diagnose.py baseline       # 看基线漏在哪
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lab_core import bigram_similarity, extract_time_window  # noqa: E402
from lab_algo import RECOMMENDED as CFG, VARIANTS, hybrid_recall  # noqa: E402
from lab_eval import build_ctx, load_goldset  # noqa: E402


def raw_candidates(ctx, query: str, limit: int = 20):
    """不过闸门、不限预算，只看 BM25 原始排序"""
    terms = ctx.tok.query_terms(query)
    kept = [t for t in terms if ctx.index.df.get(t)]
    bm = ctx.index.score(kept, k1=CFG.k1, b=CFG.b)
    return sorted(bm.items(), key=lambda x: -x[1])[:limit], kept


def main() -> None:
    variant = sys.argv[1] if len(sys.argv) > 1 else "hybrid4"
    ctx = build_ctx()
    goldset = load_goldset()
    by_id = {d.doc_id: d for d in ctx.docs}
    fn = VARIANTS[variant]

    print(f"变体 = {variant}\n")
    for item in goldset:
        res = fn(ctx, item["text"], CFG)
        ids = res.ids
        must = item.get("must") or []
        ok = item.get("ok") or []
        if item["kind"] == "neg":
            mark = "OK " if not ids else "噪声"
            print(f"[{item['id']}] {mark} neg 注入 {len(ids)} 条 :: {item['text']}")
            for d in ids[:8]:
                print(f"        {d} | {by_id[d].event[:50]}")
            continue

        hit = [m for m in must if m in ids]
        miss = [m for m in must if m not in ids]
        raw, kept = raw_candidates(ctx, item["text"])
        raw_ids = [d for d, _ in raw]
        raw_pos = {m: (raw_ids.index(m) + 1) for m in must if m in raw_ids}
        print(f"[{item['id']}] {len(hit)}/{len(must)} 命中  「{item['text']}」")
        print(f"        词={kept}")
        for m in hit:
            print(f"        ✓ {m} 第{ids.index(m)+1}位 | {by_id[m].event[:46]}")
        for m in miss:
            rank = raw_pos.get(m)
            where = f"BM25#{rank}" if rank else "BM25 top20 外"
            print(f"        ✗ {m} {where} | {by_id[m].event[:46]}")
        extra = [d for d in ids if d not in must and d not in ok]
        for d in extra[:4]:
            print(f"        · 噪声 {d} | {by_id[d].event[:46]}")
        print()


if __name__ == "__main__":
    main()
