# -*- coding: utf-8 -*-
"""记忆召回实验室 · 评测与网格搜索

指标口径（全部在 top-k=8 的同等预算下比较，避免「返回多所以命中多」的假优势）：
  recall_must  : 核心答案被召回的条数 / 核心答案总数（宏平均，正例）
  prec_rel     : 召回结果中「核心 + 相关」所占比例（宏平均，仅统计有返回的正例）
  mrr          : 第一条核心答案名次的倒数（宏平均，正例）
  empty_pos    : 正例里返回 0 条的数量（漏答）
  neg_noise    : 负例平均注入条数（越低越好，理想 0）
  neg_zero     : 负例里返回 0 条的比例
  avg_n        : 全部查询平均注入条数（提示词预算代理）
  avg_chars    : 按生产格式渲染后的平均字符数
  ms           : 单次召回平均耗时
"""
from __future__ import annotations

import io
import json
import os
import statistics
import sys
import time
from dataclasses import replace
from typing import Dict, List, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from lab_core import (  # noqa: E402
    BigramIndex,
    Doc,
    EntityIndex,
    InvertedIndex,
    MonthIndex,
    TagIndex,
    Tokenizer,
    load_records,
    prime_jieba,
)
from lab_algo import (  # noqa: E402
    VARIANTS,
    Cfg,
    Ctx,
    Result,
    baseline_recall,
    hybrid_recall,
    minimal_recall,
)

TOP_K = 8


# ─────────────────────────── 环境构建 ───────────────────────────
def build_ctx(use_userdict: bool = False, userdict_max_len: int = 99) -> Ctx:
    """默认不灌用户词典 —— 消融显示它净负收益（见 ablate_dict.py）。"""
    prime_jieba()
    docs = load_records()
    tok = Tokenizer(docs, use_userdict=use_userdict, userdict_max_len=userdict_max_len)
    return Ctx(
        docs=docs,
        tok=tok,
        index=InvertedIndex.build(docs, tok),
        entity=EntityIndex.build(docs),
        month=MonthIndex.build(docs),
        bigram=BigramIndex.build(docs),
        tagindex=TagIndex.build(docs),
    )


def load_goldset() -> List[dict]:
    with open(os.path.join(HERE, "goldset.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)["queries"]


# ─────────────────────────── 指标 ───────────────────────────
def _fmt_time(ts: str) -> str:
    parts = str(ts or "").split("-")
    return f"{parts[0]}-{parts[1]}-{parts[2]} {parts[3]}:{parts[4]}" if len(parts) >= 5 else str(ts or "")


def render_chars(ctx: Ctx, ids: Sequence[str]) -> int:
    """按主程序生产格式估算注入字符数（含元数据前缀）"""
    by_id = {d.doc_id: d for d in ctx.docs}
    total = len("# 喵呜的记忆")
    for did in ids:
        d = by_id.get(did)
        if not d:
            continue
        meta = f"话题:{'、'.join(d.topics)}"
        if d.tags:
            meta += f" | 标签:{'、'.join(d.tags)}"
        if d.joint_names:
            meta += f" | 参与:{'、'.join(d.joint_names)}"
        when = _fmt_time(d.time)
        if when:
            meta += f" | 时间:{when}"
        total += len(f"- [{meta}] {d.event}")
    return total


def evaluate(ctx: Ctx, runner, goldset: Sequence[dict], k: int = TOP_K) -> Dict[str, float]:
    recall, prec, mrr = [], [], []
    empty_pos = 0
    neg_noise, neg_zero = [], 0
    all_n, all_chars, times = [], [], []
    per_query: List[Tuple[str, List[str]]] = []

    for item in goldset:
        t0 = time.perf_counter()
        res: Result = runner(ctx, item["text"])
        times.append((time.perf_counter() - t0) * 1000)
        ids = res.ids[:k]
        per_query.append((item["id"], ids))
        all_n.append(len(res.ids))
        all_chars.append(render_chars(ctx, ids))

        if item["kind"] == "pos":
            must = set(item.get("must") or [])
            ok = set(item.get("ok") or [])
            if not ids:
                empty_pos += 1
                recall.append(0.0)
                mrr.append(0.0)
                continue
            hit_must = len(set(ids) & must)
            recall.append(hit_must / len(must) if must else 0.0)
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
    return {
        "recall_must": avg(recall),
        "prec_rel": avg(prec),
        "mrr": avg(mrr),
        "empty_pos": float(empty_pos),
        "neg_noise": round(sum(neg_noise) / neg_count, 2),
        "neg_zero": round(neg_zero / neg_count, 3),
        "avg_n": round(sum(all_n) / len(all_n), 2),
        "avg_chars": int(sum(all_chars) / max(1, len(all_chars))),
        "ms": round(sum(times) / max(1, len(times)), 2),
        "_per_query": per_query,
    }


def composite(m: Dict[str, float]) -> float:
    """综合分 = F1(prec_rel, recall_must) − 负例噪声惩罚 − 漏答惩罚

    为什么用 F1 而不是加权和：加权和会被量纲和权重选择绑架；
    F1 对「召回高但全是噪声」（现状：P=0.30/R=0.72）和「干净但漏答」（bigram 单路：P=0.86/R=0.33）
    给出同样低的评价——这正是我们要的：两者都不算好。
    """
    p, r = m["prec_rel"], m["recall_must"]
    f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
    return f1 - 0.3 * (m["neg_noise"] / TOP_K) - 0.02 * m["empty_pos"]


# ─────────────────────────── 变体对照 ───────────────────────────
def run_variants(ctx: Ctx, goldset: Sequence[dict], cfg: Cfg) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    for name, fn in VARIANTS.items():
        out[name] = evaluate(ctx, lambda c, q, _f=fn: _f(c, q, cfg), goldset)
    return out


def print_variant_table(results: Dict[str, Dict]) -> None:
    cols = ["综合", "recall_must", "prec_rel", "mrr", "empty_pos", "neg_noise", "neg_zero",
            "avg_n", "avg_chars", "ms"]
    width = max(len(n) for n in results) + 2
    print(f"{'变体':<{width}}" + "".join(f"{c:>12}" for c in cols))
    print("-" * (width + 12 * len(cols)))
    for name, m in sorted(results.items(), key=lambda x: -composite(x[1])):
        row = [f"{composite(m):.3f}", f"{m['recall_must']:.3f}", f"{m['prec_rel']:.3f}",
               f"{m['mrr']:.3f}", f"{int(m['empty_pos'])}", f"{m['neg_noise']:.2f}",
               f"{m['neg_zero']:.2f}", f"{m['avg_n']:.1f}", f"{m['avg_chars']}",
               f"{m['ms']:.1f}"]
        print(f"{name:<{width}}" + "".join(f"{c:>12}" for c in row))


# ─────────────────────────── 网格搜索 ───────────────────────────
def grid_search(ctx: Ctx, goldset: Sequence[dict], verbose: bool = True) -> Cfg:
    """坐标下降：逐阶段扫参，保留每阶段最优。"""
    base = Cfg()
    stages: List[Tuple[str, List[dict]]] = [
        ("BM25 k1/b", [{"k1": k, "b": b}
                       for k in (0.9, 1.2, 1.5) for b in (0.5, 0.75, 1.0)]),
        ("闸门", [{"gate_mode": g, "gate_value": v}
                  for g, v in (("p75", 0.0), ("p50", 0.0), ("ratio", 0.2), ("ratio", 0.3),
                               ("ratio", 0.5), ("abs", 0.5), ("abs", 1.0), ("abs", 2.0),
                               ("none", 0.0))]),
        ("字二元通道", [{"use_bigram": u, "bigram_min_hits": h}
                        for u in (True, False) for h in (2, 3)]),
        ("tag 通道", [{"use_tag": u, "tag_gate": g, "tag_can_gate": c}
                     for u in (True, False) for g in (1.5, 2.5, 3.5) for c in (True, False)
                     if u or (g == 2.5 and c is True)]),
        ("选词", [{"max_df_ratio": r, "max_terms": t}
                  for r in (0.0, 0.10, 0.20, 0.30) for t in (0, 5, 8)]),
        ("预算", [{"core_n": c, "supp_n": s, "min_keep": m}
                  for c, s in ((3, 5), (2, 4), (3, 7), (2, 6), (4, 4)) for m in (0, 1)]),
        ("字段权重", [{"field_event": 1.0, "field_tags": t, "field_joint": j}
                      for t, j in ((0.5, 0.3), (0.8, 0.5), (0.3, 0.2), (1.0, 0.6))]),
        ("查询清洗", [{"drop_nickname": n, "drop_noise": s}
                      for n in (True, False) for s in (True, False)]),
        ("通道开关", [{"_entity": e, "_time": t}
                      for e in (True, False) for t in (True, False)]),
    ]

    best_cfg = base
    best_score = -9e9
    for pass_no in range(2):
        for stage_name, options in stages:
            rows = []
            for raw_opt in options:
                opt = dict(raw_opt)
                ent = opt.pop("_entity", True)
                tim = opt.pop("_time", True)
                cfg = replace(best_cfg, **opt)
                m = evaluate(ctx, lambda c, q, _c=cfg, _e=ent, _t=tim:
                             hybrid_recall(c, q, _c, use_entity=_e, use_time=_t), goldset)
                rows.append((composite(m), cfg, m, ent, tim))
            rows.sort(key=lambda x: -x[0])
            top_s, top_cfg, top_m, top_ent, top_tim = rows[0]
            if top_s > best_score + 1e-9:
                best_score, best_cfg = top_s, top_cfg
            if verbose and pass_no == 0:
                diff = {k: v for k, v in vars(top_cfg).items()
                        if v != getattr(base, k, None)}
                print(f"\n[阶段{pass_no+1}] {stage_name:<10} 综合={top_s:.4f} "
                      f"recall={top_m['recall_must']:.3f} prec={top_m['prec_rel']:.3f} "
                      f"noise={top_m['neg_noise']:.2f}  改动={diff}")
    if verbose:
        print(f"\n[最终] 综合={best_score:.4f}")
    return best_cfg


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ctx = build_ctx()
    goldset = load_goldset()
    pos = sum(1 for q in goldset if q["kind"] == "pos")
    neg = len(goldset) - pos
    print(f"语料 {len(ctx.docs)} 条 | 评测集 {len(goldset)} 条（正例 {pos} / 负例 {neg}）| top-k={TOP_K}\n")

    print("=" * 30 + " 一、各方案对照（默认参数） " + "=" * 30)
    print_variant_table(run_variants(ctx, goldset, Cfg()))

    print("\n" + "=" * 30 + " 二、网格搜索（坐标下降） " + "=" * 30)
    best = grid_search(ctx, goldset)

    print("\n" + "=" * 30 + " 三、最优配置下的对照 " + "=" * 30)
    print_variant_table(run_variants(ctx, goldset, best))

    print("\n最优配置（Cfg）：")
    for k, v in vars(best).items():
        print(f"  {k} = {v}")

    out = {
        "best_cfg": vars(best),
        "metrics": {k: v for k, v in
                    run_variants(ctx, goldset, best).items()
                    for k2, v2 in v.items() if k2 != "_per_query"},
    }
    with open(os.path.join(HERE, "lab_result.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("\n已写入 lab_result.json")


if __name__ == "__main__":
    main()
