# -*- coding: utf-8 -*-
"""把本地文件推到 AutoDL，并可选地远端执行一条命令。

为什么单独写一个
----------------
* 命令行的引号在 PowerShell 里会被吃掉（之前踩过），所以"要跑的命令"也从文件读。
* 密码沿用 autoDL/密码.txt，**不打印**。

用法
----
    # 只上传
    python cloud_push.py --put .scripts/a.py:/root/autodl-tmp/a.py

    # 上传多个 + 跑命令（命令从本地文件读）
    python cloud_push.py --put x.py:/root/x.py --run-file .scripts/run.sh

    # 只跑命令
    python cloud_push.py --run-file .scripts/run.sh

目录不存在会自动 mkdir -p。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

MODULE_ROOT = Path(__file__).resolve().parents[1]
def _autodl_dir() -> Path:
    """凭据目录：优先 labs/autoDL（用户把它挪到了 labs 下），退回模块根的 autoDL。"""
    for cand in (MODULE_ROOT / "labs" / "autoDL", MODULE_ROOT / "autoDL"):
        if cand.is_dir():
            return cand
    return MODULE_ROOT / "autoDL"


AUTODL_DIR = _autodl_dir()


def find_password() -> Path | None:
    if not AUTODL_DIR.is_dir():
        return None
    for item in AUTODL_DIR.iterdir():
        if not item.is_file():
            continue
        name = item.name.lower()
        if name in ("密码.txt", "password.txt", "passwd.txt", "密码", "password"):
            return item
    for item in AUTODL_DIR.iterdir():
        if item.is_file() and ("密码" in item.name or "pass" in item.name.lower()):
            return item
    return None


def parse_login() -> tuple[str, int, str]:
    import re

    text = (AUTODL_DIR / "登录指令.txt").read_text(encoding="utf-8", errors="replace")
    host_match = re.search(r"(?:^|\s)([\w.\-]+@[\w.\-]+)", text)
    port_match = re.search(r"-p\s+(\d+)", text)
    if not host_match or not port_match:
        raise SystemExit("无法从 登录指令.txt 解析 host/port")
    user, host = host_match.group(1).split("@", 1)
    return user, int(port_match.group(1)), host


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--put", action="append", default=[],
                        help="本地路径:远端路径（可重复）")
    parser.add_argument("--run-file", default=None, help="把该本地文件内容作为远端命令执行")
    parser.add_argument("--run", default=None, help="直接指定远端命令（注意引号）")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    if not args.put and not args.run_file and not args.run:
        print(__doc__)
        return 2

    import paramiko

    user, port, host = parse_login()
    pw_path = find_password()
    if not pw_path:
        raise SystemExit(f"找不到密码文件（放在 {AUTODL_DIR} 下）")
    password = pw_path.read_text(encoding="utf-8", errors="replace").strip()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"连接 {user}@{host}:{port} …")
    client.connect(hostname=host, port=port, username=user, password=password,
                   timeout=25, auth_timeout=25, banner_timeout=25,
                   allow_agent=False, look_for_keys=False)
    print("已连接。")

    try:
        if args.put:
            sftp = client.open_sftp()
            try:
                for spec in args.put:
                    if ":" not in spec:
                        print(f"  ! 跳过（缺少 ':'）：{spec}")
                        continue
                    # 用最后一个冒号切分：否则 Windows 的 "D:\..." 会被从盘符切开
                    local_s, remote = spec.rsplit(":", 1)
                    local = Path(local_s)
                    if not local.is_absolute():
                        local = MODULE_ROOT / local_s
                    if not local.is_file():
                        print(f"  ✗ 本地不存在：{local}")
                        return 3
                    # 远端目录
                    remote_dir = os.path.dirname(remote) or "/"
                    try:
                        sftp.stat(remote_dir)
                    except IOError:
                        client.exec_command(f"mkdir -p '{remote_dir}'")[1].channel.recv_exit_status()
                    sftp.put(str(local), remote)
                    size = os.path.getsize(local)
                    print(f"  ✓ {local.name} -> {remote}  ({size:,} 字节)")
            finally:
                sftp.close()

        cmd = args.run
        if args.run_file:
            cmd = Path(args.run_file).read_text(encoding="utf-8")
        if cmd:
            print("\n--- 远端输出 ---")
            stdin, stdout, stderr = client.exec_command(cmd, timeout=args.timeout)
            sys.stdout.write(stdout.read().decode("utf-8", "replace"))
            err = stderr.read().decode("utf-8", "replace")
            if err.strip():
                sys.stdout.write("\n[stderr]\n" + err)
            code = stdout.channel.recv_exit_status()
            print(f"\n--- 退出码 {code} ---")
            return 0 if code == 0 else 1
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
