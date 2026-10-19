# -*- coding: utf-8 -*-
# scripts/clean_kb_pollution.py
# 清理知识库里被反爬挑战页/错误页污染的 chunk（只删污染块，不动正常内容）
#
# 用法：
#   python scripts/clean_kb_pollution.py            # 只报告，不删除（默认）
#   python scripts/clean_kb_pollution.py --apply    # 真正删除
#
# 判定标准只用 content_quality.find_marker（反爬/错误页标记），
# 不用 is_junk —— 后者含「过短」规则，会误删正常的尾部 chunk。

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

COLLECTION = "knowledge"


def main():
    ap = argparse.ArgumentParser(description="清理知识库污染 chunk")
    ap.add_argument("--apply", action="store_true", help="真正执行删除（默认只报告）")
    ap.add_argument("--db", default=os.path.join(".vendor", ".DataBase", "chroma"),
                    help="ChromaDB 持久化目录")
    args = ap.parse_args()

    from func.database.search.content_quality import find_marker
    import chromadb

    db_dir = args.db if os.path.isabs(args.db) else os.path.join(ROOT, args.db)
    if not os.path.isdir(db_dir):
        print(f"目录不存在: {db_dir}")
        return 1
    print(f"ChromaDB: {db_dir}")

    client = chromadb.PersistentClient(path=db_dir)
    col = client.get_or_create_collection(name=COLLECTION, metadata={"hnsw:space": "cosine"})

    total = col.count()
    print(f"集合 {COLLECTION} 共 {total} 个 chunk")

    # 全量取回（2814 条规模可一次读完；量大时按 offset 分批）
    got = col.get(include=["documents", "metadatas"])
    ids = got.get("ids") or []
    docs = got.get("documents") or []
    metas = got.get("metadatas") or []

    hits = []          # [(id, doc_name, marker)]
    for i, cid in enumerate(ids):
        doc = docs[i] if i < len(docs) else ""
        marker = find_marker(doc)
        if not marker:
            continue
        meta = metas[i] if i < len(metas) else {}
        hits.append((cid, str((meta or {}).get("doc_name") or ""), marker))

    if not hits:
        print("\n未发现污染 chunk，无需清理 ✅")
        return 0

    print(f"\n发现 {len(hits)} 个污染 chunk：\n")
    per_doc = {}
    for cid, name, marker in hits:
        per_doc[name] = per_doc.get(name, 0) + 1
    print(f"  {'doc_name':<28}{'污染chunk':>10}  原因")
    for name, n in sorted(per_doc.items(), key=lambda x: -x[1]):
        marker = next(m for _i, nm, m in hits if nm == name)
        print(f"  {name[:26]:<28}{n:>10}  {marker}")

    if not args.apply:
        print(f"\n[只报告] 未做任何修改。确认无误后执行：")
        print(f"  runtime\\311\\python.exe scripts\\clean_kb_pollution.py --apply")
        return 0

    print(f"\n开始删除 {len(hits)} 个 chunk …")
    col.delete(ids=[h[0] for h in hits])

    remain = col.count()
    print(f"删除完成：{total} → {remain}（减少 {total - remain}）")

    # 复核
    got2 = col.get(include=["documents"])
    left = sum(1 for d in (got2.get("documents") or []) if find_marker(d))
    print(f"复核：库内剩余污染 chunk = {left}")
    if left:
        print("⚠️ 仍有残留，请重跑本脚本")
        return 2
    print("✅ 清理干净")
    return 0


if __name__ == "__main__":
    sys.exit(main())
