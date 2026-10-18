# -*- coding: utf-8 -*-
# .scripts/pull_dmem.py
"""把云端 δ-mem 的**每用户状态**拉到本地（无卡模式也能跑，只走 SSH/SFTP）。

为什么需要：δ-mem 的状态是**服务端**写的，服务端在 AutoDL 上。主项目只发
`POST /control/dmem/write`，本地不会产生任何 `mem/` 文件。想离线检查/备份/
迁移这些状态，就得主动拉一次。

默认镜像关系（保持与云端同一套相对路径，便于直接对拷）：

    远端  <REMOTE_ROOT>/labs/.lab/userinfo/<uid>/mem/*      ← 实验沙箱里的真实数据
    本地  <MODULE_ROOT>/labs/.lab/userinfo/<uid>/mem/*

可选 `--real`：再把 `--only` 指定的用户（默认 000001）复制一份到**正式目录**

    本地  <MODULE_ROOT>/character/userinfo/<uid>/mem/*

用法
----
    python .scripts/pull_dmem.py                 # 全量镜像到 labs/.lab/userinfo
    python .scripts/pull_dmem.py --only 000001   # 只拉一个用户
    python .scripts/pull_dmem.py --real          # 镜像 + 000001 复制到正式目录
    python .scripts/pull_dmem.py --list          # 只看云端有哪些用户、多大
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import posixpath
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE_ROOT = HERE.parent


def _load_cloud():
    spec = importlib.util.spec_from_file_location("cloud_serve", str(HERE / "cloud_serve.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _walk(sftp, root: str):
    """递归列出远端文件：(相对路径, 大小)。"""
    out = []
    stack = [""]
    while stack:
        rel = stack.pop()
        full = posixpath.join(root, rel) if rel else root
        try:
            entries = sftp.listdir_attr(full)
        except IOError:
            continue
        for ent in entries:
            child = posixpath.join(rel, ent.filename) if rel else ent.filename
            mode = ent.st_mode or 0
            if (mode & 0o170000) == 0o040000:      # 目录
                stack.append(child)
            else:
                out.append((child, ent.st_size or 0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="把云端 δ-mem 每用户状态拉到本地")
    ap.add_argument("--src", default="", help="远端源目录（默认 <REMOTE_ROOT>/labs/.lab/userinfo）")
    ap.add_argument("--dst", default="", help="本地目标目录（默认 <MODULE_ROOT>/labs/.lab/userinfo）")
    ap.add_argument("--only", default="", help="只处理这些 uid，逗号分隔，如 000001,000002")
    ap.add_argument("--real", action="store_true",
                    help="再把 --only（默认 000001）复制到 character/userinfo/<uid>/mem")
    ap.add_argument("--list", action="store_true", help="只列云端用户与体积，不下载")
    args = ap.parse_args()

    cs = _load_cloud()
    client, user, host, port = cs.connect()
    print(f"已连接 {user}@{host}:{port}")
    sftp = client.open_sftp()

    src_root = args.src or (cs.REMOTE_ROOT + "/labs/.lab/userinfo")
    dst_root = Path(args.dst) if args.dst else (MODULE_ROOT / "labs" / ".lab" / "userinfo")
    only = {x.strip() for x in args.only.split(",") if x.strip()} or None

    # 有哪些用户
    try:
        users = [e.filename for e in sftp.listdir_attr(src_root)
                 if (e.st_mode or 0) & 0o170000 == 0o040000]
    except IOError as exc:
        print(f"读不到源目录 {src_root}: {exc}")
        sftp.close(); client.close()
        return 2
    users.sort()
    print(f"云端用户 {len(users)} 个: {', '.join(users)}")

    if args.list:
        for uid in users:
            total = sum(sz for _p, sz in _walk(sftp, posixpath.join(src_root, uid)))
            print(f"  {uid}  {total/1024:8.1f} KB")
        sftp.close(); client.close()
        return 0

    picked = [u for u in users if (only is None or u in only)]
    total_files = total_bytes = 0
    for uid in picked:
        remote_uid = posixpath.join(src_root, uid)
        files = _walk(sftp, remote_uid)
        if not files:
            print(f"  {uid}: 空，跳过")
            continue
        uid_bytes = 0
        for rel, size in files:
            remote = posixpath.join(remote_uid, rel)
            local = dst_root / uid / Path(rel.replace("/", os.sep))
            local.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(remote, str(local))
            uid_bytes += size
            total_files += 1
        total_bytes += uid_bytes
        print(f"  {uid}: {len(files)} 个文件, {uid_bytes/1024:.1f} KB -> {dst_root / uid}")

    print(f"\n合计 {len(picked)} 个用户 / {total_files} 个文件 / {total_bytes/1024:.1f} KB")
    print(f"落点: {dst_root}")

    # 可选：把指定用户复制到「正式目录」，便于本地服务或人工检查
    if args.real:
        targets = only or {"000001"}
        for uid in sorted(targets):
            src = dst_root / uid / "mem"
            if not src.is_dir():
                print(f"  --real 跳过 {uid}（没有 mem/ 目录）")
                continue
            dst = MODULE_ROOT / "character" / "userinfo" / uid / "mem"
            dst.mkdir(parents=True, exist_ok=True)
            copied = 0
            for item in src.rglob("*"):
                if item.is_file():
                    out = dst / item.relative_to(src)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(item.read_bytes())
                    copied += 1
            print(f"  --real {uid}: {copied} 个文件 -> {dst}")

    sftp.close()
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
