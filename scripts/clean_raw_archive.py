# -*- coding: utf-8 -*-
# scripts/clean_raw_archive.py
# 清理 .vendor/.DataBase/raw 归档目录（纯归档，无任何代码读取，删除不影响知识库）
#
# 清理三类：
#   1) 反爬验证页 / 错误页 / 过短内容的 content.txt（垃圾）
#   2) 内容完全相同的重复 content.txt（按 md5 只留一份）
#   3) 清完 task 后变空的批次目录
#
# 用法：
#   python scripts/clean_raw_archive.py            # 只报告
#   python scripts/clean_raw_archive.py --apply    # 真正删除
#   python scripts/clean_raw_archive.py --apply --drop-batch-meta   # 顺带删 _batch_meta.json

import argparse
import hashlib
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def md5_of_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def batches_without_content(raw: str, pending_delete=None) -> list:
    """列出没有任何 content.txt 的批次目录（可选排除即将删除的 task）"""
    out = []
    for batch in os.listdir(raw):
        bdir = os.path.join(raw, batch)
        if not os.path.isdir(bdir):
            continue
        found = False
        for dirpath, _dirnames, filenames in os.walk(bdir):
            if dirpath in (pending_delete or set()):
                continue
            if "content.txt" in filenames:
                found = True
                break
        if not found:
            out.append(bdir)
    return out


def main():
    ap = argparse.ArgumentParser(description="清理 raw 归档目录")
    ap.add_argument("--apply", action="store_true", help="真正删除（默认只报告）")
    ap.add_argument("--drop-batch-meta", action="store_true",
                    help="同时删除 _batch_meta.json（仅审计用途）")
    ap.add_argument("--drop-orphan", action="store_true",
                    help="同时删除只有 meta.json、没有 content.txt 的空壳 task 目录")
    ap.add_argument("--drop-empty-batches", action="store_true",
                    help="同时删除没有任何 content.txt 的批次目录（含其 _batch_meta.json）")
    ap.add_argument("--raw", default=os.path.join(".vendor", ".DataBase", "raw"))
    args = ap.parse_args()

    raw = args.raw if os.path.isabs(args.raw) else os.path.join(ROOT, args.raw)
    if not os.path.isdir(raw):
        print(f"目录不存在: {raw}")
        return 1

    from func.database.search.content_quality import is_junk

    # 1. 枚举所有 task 的 content.txt
    tasks = []          # [{task_dir, content, batch}]
    for dirpath, _dirnames, filenames in os.walk(raw):
        if "content.txt" not in filenames:
            continue
        tasks.append({
            "task_dir": dirpath,
            "content": os.path.join(dirpath, "content.txt"),
            "batch": os.path.basename(os.path.dirname(dirpath)),
        })
    tasks.sort(key=lambda t: t["content"])

    before_files = sum(len(f) for _d, _s, f in os.walk(raw))
    before_size = sum(
        os.path.getsize(os.path.join(p, n))
        for p, _d, fs in os.walk(raw) for n in fs
    )

    print(f"raw 归档: {before_files} 文件 / {before_size / 1024 / 1024:.2f} MB")
    print(f"task 数（含 content.txt）: {len(tasks)}")

    to_delete = []      # [(task_dir, reason)]
    kept_md5 = {}       # md5 -> 首个保留的 task_dir

    junk_n = dup_n = 0
    for t in tasks:
        try:
            with open(t["content"], "r", encoding="utf-8") as f:
                text = f.read()
            digest = md5_of_file(t["content"])
        except Exception as e:
            print(f"  读取失败，跳过: {t['content']} ({e})")
            continue

        junk, reason = is_junk(text)
        if junk:
            to_delete.append((t["task_dir"], f"垃圾内容:{reason}"))
            junk_n += 1
            continue

        if digest in kept_md5:
            keep_rel = os.path.relpath(kept_md5[digest], raw).replace("\\", "/")
            to_delete.append((t["task_dir"], f"与 {keep_rel} 内容完全相同"))
            dup_n += 1
            continue

        kept_md5[digest] = t["task_dir"]

    print(f"\n判定：")
    print(f"  垃圾内容      : {junk_n}")
    print(f"  完全重复      : {dup_n}")
    print(f"  保留          : {len(kept_md5)}")
    print(f"  合计待删 task : {len(to_delete)}")

    if junk_n or dup_n:
        print(f"\n  待删明细（前 20）：")
        for d, r in to_delete[:20]:
            rel = os.path.relpath(d, raw).replace("\\", "/")
            print(f"    {rel:<34} {r}")

    # 2. 预估删除后的空批次
    deleting = {d for d, _r in to_delete}
    empty_batches = []
    for batch in os.listdir(raw):
        bdir = os.path.join(raw, batch)
        if not os.path.isdir(bdir):
            continue
        left = []
        for name in os.listdir(bdir):
            p = os.path.join(bdir, name)
            if os.path.isdir(p) and p not in deleting:
                left.append(name)
        if not left:
            empty_batches.append(bdir)
    print(f"\n  清完后将变空/已空的批次目录: {len(empty_batches)}")

    # 空壳 task 目录：只有 meta.json、没有 content.txt（失败任务的残留记录）
    orphans = []
    for dirpath, _dirnames, filenames in os.walk(raw):
        if "meta.json" in filenames and "content.txt" not in filenames:
            orphans.append(dirpath)
    print(f"  空壳 task 目录（只有 meta.json）: {len(orphans)}"
          + ("  → 将删除" if args.drop_orphan else "  （加 --drop-orphan 可删）"))

    no_content = batches_without_content(raw, deleting)
    print(f"  没有正文的批次目录: {len(no_content)}"
          + ("  → 将整目录删除" if args.drop_empty_batches
             else "  （加 --drop-empty-batches 可整目录删除）"))

    if not args.apply:
        print(f"\n[只报告] 未做任何修改。确认后执行：")
        print(f"  runtime\\311\\python.exe scripts\\clean_raw_archive.py --apply")
        return 0

    # 3. 执行删除
    manifest = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "raw": raw,
        "removed_tasks": [{"dir": d, "reason": r} for d, r in to_delete],
        "removed_batches": empty_batches,
        "drop_batch_meta": args.drop_batch_meta,
    }
    removed = 0
    for d, _r in to_delete:
        try:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
        except Exception as e:
            print(f"  删除失败: {d} ({e})")

    batch_removed = 0
    for bdir in empty_batches:
        try:
            if args.drop_batch_meta:
                shutil.rmtree(bdir, ignore_errors=True)
            else:
                for name in os.listdir(bdir):
                    p = os.path.join(bdir, name)
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
            batch_removed += 1
        except Exception as e:
            print(f"  批次清理失败: {bdir} ({e})")

    # 空壳 task 目录：只有 meta.json、没有 content.txt（失败任务的残留记录）
    if args.drop_orphan:
        n = 0
        for d in orphans:
            try:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
            except Exception:
                pass
        print(f"  删除空壳 task 目录: {n}")

    if args.drop_empty_batches:
        # 重新计算（task 删除后可能有更多批次变空）
        targets = batches_without_content(raw)
        n = 0
        for d in targets:
            try:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
            except Exception:
                pass
        print(f"  删除无正文批次目录: {n}")
        manifest["removed_no_content_batches"] = targets

    if args.drop_batch_meta:
        n = 0
        for dirpath, _d, filenames in os.walk(raw):
            if "_batch_meta.json" in filenames:
                try:
                    os.remove(os.path.join(dirpath, "_batch_meta.json"))
                    n += 1
                except Exception:
                    pass
        print(f"  删除 _batch_meta.json: {n}")

    after_files = sum(len(f) for _d, _s, f in os.walk(raw))
    after_size = sum(
        os.path.getsize(os.path.join(p, n))
        for p, _d, fs in os.walk(raw) for n in fs
    )

    manifest["after_files"] = after_files
    manifest["after_size"] = after_size
    try:
        mpath = os.path.join(os.path.dirname(raw),
                             f"raw_cleanup_manifest_{time.strftime('%Y%m%d_%H%M%S')}.json")
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"\n清单已保存: {mpath}")
    except Exception as e:
        print(f"\n清单保存失败（不影响删除）: {e}")

    print(f"\n完成：删除 task {removed} 个、批次目录 {batch_removed} 个")
    print(f"  文件 {before_files} → {after_files}")
    print(f"  体积 {before_size / 1024 / 1024:.2f} MB → {after_size / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
