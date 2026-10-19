# -*- coding: utf-8 -*-
# scripts/backfill_source_id.py
# 把已有 web chunk 的 source_id 从旧值（每批 task 序号 "1"~"4"）换成稳定文档键
#
# 新键规则与 learning._doc_key 一致：web_<md5(url)[:16]>
#
# 用法：
#   python scripts/backfill_source_id.py            # 只报告
#   python scripts/backfill_source_id.py --apply    # 真正写入

import argparse
import hashlib
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

COLLECTION = "knowledge"


def doc_key(url: str, site: str = "", doc_name: str = "") -> str:
    basis = (url or "").strip() or f"{site}|{doc_name}"
    return "web_" + hashlib.md5(basis.encode("utf-8")).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser(description="回填 web 的 source_id")
    ap.add_argument("--apply", action="store_true", help="真正写入（默认只报告）")
    ap.add_argument("--db", default=os.path.join(".vendor", ".DataBase", "chroma"))
    args = ap.parse_args()

    import chromadb
    db_dir = args.db if os.path.isabs(args.db) else os.path.join(ROOT, args.db)
    col = chromadb.PersistentClient(path=db_dir).get_or_create_collection(
        name=COLLECTION, metadata={"hnsw:space": "cosine"})

    got = col.get(include=["metadatas"])
    ids = got.get("ids") or []
    metas = got.get("metadatas") or []
    print(f"集合 {COLLECTION} 共 {len(ids)} 个 chunk")

    old_dist = Counter()
    updates_ids = []
    updates_metas = []
    for i, cid in enumerate(ids):
        m = dict(metas[i] or {})
        if (m.get("source_type") or "") != "web":
            continue
        old = str(m.get("source_id") or "")
        old_dist[old] += 1
        new = doc_key(m.get("url") or "", m.get("site") or "", m.get("doc_name") or "")
        if new == old:
            continue
        m["source_id"] = new
        updates_ids.append(cid)
        updates_metas.append(m)

    print(f"\nweb chunk 的旧 source_id 分布（前 8）:")
    for v, c in old_dist.most_common(8):
        print(f"  {v!r:<26} {c}")

    print(f"\n需要更新: {len(updates_ids)} 个 chunk")
    if not updates_ids:
        print("无需回填 ✅")
        return 0

    sample = Counter(m["source_id"] for m in updates_metas)
    print(f"将产生 {len(sample)} 个不同文档键，前 5:")
    for v, c in sample.most_common(5):
        print(f"  {v}  {c} chunk")

    if not args.apply:
        print("\n[只报告] 未写入。确认后执行：")
        print("  runtime\\311\\python.exe scripts\\backfill_source_id.py --apply")
        return 0

    batch = 500
    done = 0
    for i in range(0, len(updates_ids), batch):
        part_ids = updates_ids[i:i + batch]
        part_metas = updates_metas[i:i + batch]
        col.update(ids=part_ids, metadatas=part_metas)
        done += len(part_ids)
        print(f"  已更新 {done}/{len(updates_ids)}")

    print(f"\n完成：更新 {done} 个 chunk")
    # 复核
    got2 = col.get(include=["metadatas"])
    left = sum(1 for m in (got2.get("metadatas") or [])
               if (m or {}).get("source_type") == "web"
               and not str((m or {}).get("source_id") or "").startswith("web_"))
    print(f"复核：仍是旧格式的 web chunk = {left}")
    return 0 if left == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
