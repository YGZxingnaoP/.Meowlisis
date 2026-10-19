# -*- coding: utf-8 -*-
# scripts/clean_kb_duplicates.py
# 清理知识库里文本完全相同的冗余 chunk（每组只留一份，其余删除）
#
# 用法：
#   python scripts/clean_kb_duplicates.py            # 只报告
#   python scripts/clean_kb_duplicates.py --apply    # 真正删除
#
# 判定方式与入库去重一致：chunk 文本 md5 指纹相同即视为同一内容，不做模糊匹配。

import argparse
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

COLLECTION = "knowledge"


def main():
    ap = argparse.ArgumentParser(description="清理知识库冗余 chunk")
    ap.add_argument("--apply", action="store_true", help="真正执行删除（默认只报告）")
    ap.add_argument("--db", default=os.path.join(".vendor", ".DataBase", "chroma"))
    args = ap.parse_args()

    from func.database.store.vector_db import doc_digest
    import chromadb

    db_dir = args.db if os.path.isabs(args.db) else os.path.join(ROOT, args.db)
    client = chromadb.PersistentClient(path=db_dir)
    col = client.get_or_create_collection(name=COLLECTION, metadata={"hnsw:space": "cosine"})

    total = col.count()
    print(f"集合 {COLLECTION} 共 {total} 个 chunk")

    got = col.get(include=["documents", "metadatas"])
    ids = got.get("ids") or []
    docs = got.get("documents") or []
    metas = got.get("metadatas") or []

    seen = {}              # digest -> 保留的 chunk id
    dup_ids = []           # 待删 id
    dup_detail = []        # (digest, doc_name, url)
    per_doc = Counter()    # doc_name -> 冗余数

    for i, cid in enumerate(ids):
        doc = docs[i] if i < len(docs) else ""
        if not doc or not str(doc).strip():
            continue
        dg = doc_digest(doc)
        if dg in seen:
            dup_ids.append(cid)
            m = metas[i] if i < len(metas) else {}
            name = str((m or {}).get("doc_name") or "")
            per_doc[name] += 1
            dup_detail.append((dg, name, str((m or {}).get("url") or "")))
        else:
            seen[dg] = cid

    print(f"不同内容（指纹）: {len(seen)}")
    print(f"冗余 chunk       : {len(dup_ids)}"
          f"  ({len(dup_ids) / max(1, total) * 100:.1f}%)")

    if not dup_ids:
        print("\n没有冗余 chunk ✅")
        return 0

    print(f"\n冗余最多的 doc_name（前 12）：")
    for name, n in per_doc.most_common(12):
        print(f"  {n:>4}  {name}")

    # 单条文本重复次数 Top 5
    cnt = Counter(d for d in (docs or []) if d and str(d).strip())
    print(f"\n重复次数最多的单条内容（前 5）：")
    for text, c in cnt.most_common(5):
        if c < 2:
            break
        print(f"  {c:>3}×  {str(text)[:76].replace(chr(10), ' | ')}")

    if not args.apply:
        print(f"\n[只报告] 未做任何修改。确认后执行：")
        print(f"  runtime\\311\\python.exe scripts\\clean_kb_duplicates.py --apply")
        return 0

    print(f"\n开始删除 {len(dup_ids)} 个冗余 chunk …")
    deleted = 0
    batch = 500
    for i in range(0, len(dup_ids), batch):
        part = dup_ids[i:i + batch]
        try:
            col.delete(ids=part)
            deleted += len(part)
        except Exception as e:
            print(f"  批次删除失败: {e}")

    remain = col.count()
    print(f"删除完成：{total} → {remain}（减少 {total - remain}）")

    got2 = col.get(include=["documents"])
    left = Counter(d for d in (got2.get("documents") or []) if d and str(d).strip())
    still = sum(c - 1 for c in left.values() if c > 1)
    print(f"复核：剩余冗余 chunk = {still}")
    if still:
        print("⚠️ 仍有残留，请重跑本脚本")
        return 2
    print("✅ 清理干净")
    return 0


if __name__ == "__main__":
    sys.exit(main())
