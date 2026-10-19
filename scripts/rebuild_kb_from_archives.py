# -*- coding: utf-8 -*-
# scripts/rebuild_kb_from_archives.py
# 从本地归档重建知识库（不抓网页），走的是生产入库路径 CatLearnSourceIngest.ingest
#   → 清洗（text_clean）→ 分块 → 精确去重 → 向量化 → 写库
#
# 用法：
#   python scripts/rebuild_kb_from_archives.py                       # 只报告每来源篇数
#   python scripts/rebuild_kb_from_archives.py --source web --apply --delete-first
#   python scripts/rebuild_kb_from_archives.py --all --apply --delete-first
#
# 说明：重建不抓任何网页；但向量化会调用配置里的 embedding API（无本地模型）。

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from _bootstrap import install_log_fallback

install_log_fallback()

RAW = os.path.join(ROOT, ".vendor", ".DataBase", "raw")
SEED = os.path.join(ROOT, ".vendor", ".DataBase", "raw_seed")

# 明确不重建的文档（用户已决定删除汇总页）
SKIP_SOURCE_IDS = {"watch_overview"}
SKIP_DOC_NAMES = {"我的动画片单"}


def _read(p: str) -> str:
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _read_json(p: str) -> dict:
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def collect(source: str = "") -> list:
    """从归档收集文档 [{text, source_type, source_id, doc_name, url, site, tags}]"""
    docs = []

    # ---- web / ext_yuque / ext_watchlist：<raw>/<batch>/<task>/ ----
    for batch in sorted(os.listdir(RAW)) if os.path.isdir(RAW) else []:
        bdir = os.path.join(RAW, batch)
        if not os.path.isdir(bdir):
            continue
        if batch.startswith("ext_"):
            st = batch[4:]
        else:
            st = "web"
        if source and st != source:
            continue
        for task in sorted(os.listdir(bdir)):
            tdir = os.path.join(bdir, task)
            ct = os.path.join(tdir, "content.txt")
            if not os.path.isfile(ct):
                continue
            meta = _read_json(os.path.join(tdir, "meta.json"))
            text = _read(ct)
            if not text.strip():
                continue
            doc_name = str(meta.get("doc_name") or meta.get("search_keys")
                           or f"{batch}/{task}")
            source_id = str(meta.get("source_id") or f"{batch}/{task}")
            if source_id in SKIP_SOURCE_IDS or doc_name in SKIP_DOC_NAMES:
                continue
            url = str(meta.get("url") or "")
            if not url:
                results = meta.get("results") or []
                if results and isinstance(results[0], dict):
                    url = str(results[0].get("url") or "")
            docs.append({
                "text": text,
                "source_type": st,
                "source_id": source_id,
                "doc_name": doc_name,
                "url": url,
                "site": str(meta.get("site") or ""),
                "tags": str(meta.get("tags") or meta.get("search_keys") or ""),
            })

    # ---- seed：raw_seed/<site>/<name>.json = [{title,url,content}, ...] ----
    if os.path.isdir(SEED) and (not source or source == "seed"):
        for site in sorted(os.listdir(SEED)):
            sdir = os.path.join(SEED, site)
            if not os.path.isdir(sdir):
                continue
            for fn in sorted(os.listdir(sdir)):
                if not fn.endswith(".json"):
                    continue
                try:
                    pages = json.load(open(os.path.join(sdir, fn), encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(pages, list) or not pages:
                    continue
                text = "\n\n".join(str(p.get("content") or "")
                                   for p in pages if isinstance(p, dict))
                if not text.strip():
                    continue
                name = fn[:-5]
                docs.append({
                    "text": text,
                    "source_type": "seed",
                    "source_id": f"seed_{site}_{name}",
                    "doc_name": name,
                    "url": str(pages[0].get("url") or ""),
                    "site": site,
                    "tags": site,
                })
    return docs


def main():
    ap = argparse.ArgumentParser(description="从归档重建知识库")
    ap.add_argument("--source", default="", help="web / seed / watchlist / yuque")
    ap.add_argument("--all", action="store_true", help="重建全部来源")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认只报告）")
    ap.add_argument("--delete-first", action="store_true", help="先删除该来源的旧数据")
    args = ap.parse_args()

    if not args.all and not args.source:
        ap.error("需要 --source <类型> 或 --all")

    from collections import Counter

    docs = collect("" if args.all else args.source)
    cnt = Counter(d["source_type"] for d in docs)
    print(f"归档收集到 {len(docs)} 篇")
    for st, n in cnt.most_common():
        print(f"  {st:<12} {n} 篇")

    if not docs:
        print("没有可重建的文档")
        return 1

    # 入库路径（ingest）内部完成：去自有脚手架 → 按标题分段 → 小节内切块 → 前缀
    by_src = {}
    for d in docs:
        by_src.setdefault(d["source_type"], []).append(d)
    print(f"\n最终入库文档 {len(docs)} 篇（清洗/分段在 ingest 内完成）")

    if not args.apply:
        print("\n[只报告] 未写库。执行：")
        flag = "--all" if args.all else f"--source {args.source}"
        print(f"  runtime\\311\\python.exe scripts/rebuild_kb_from_archives.py "
              f"{flag} --apply --delete-first")
        return 0

    from func.database.store.source_ingest import CatLearnSourceIngest
    from func.database.store.vector_db import CatLearnVectorDB

    vdb = CatLearnVectorDB()
    if args.delete_first:
        for st in by_src:
            n = vdb.delete_source(st)
            print(f"  已删除旧来源 {st}: {n} chunk")

    stats = CatLearnSourceIngest().ingest(docs, archive=False)
    print(f"\n重建结果: {stats}")
    print(f"collection 现有: {vdb._collection.count()} chunk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
