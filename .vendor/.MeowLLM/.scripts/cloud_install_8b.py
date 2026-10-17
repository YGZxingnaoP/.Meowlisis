# -*- coding: utf-8 -*-
"""在**本地**运行，把 8B 模型**装到云端**，进度条显示在本地。

做法
----
1. 用 paramiko 连 AutoDL（密码读 autoDL/密码.txt，绝不打印）
2. 把 `.scripts/remote_fetch.py` 传上去
3. 远端执行它；它把进度写成 `PROG\\t已完成\\t总量\\t文件名` 行
4. 本地逐行解析 → 一条 tqdm 总进度条（已下/总量、速度、剩余时间）

只读云端、只写模型目录；**不需要 GPU**，无卡模式也能装。

用法（在 .vendor/.MeowLLM 目录下）
---------------------------------
    # 先看一眼要下什么（不下载）
    ..\\..\\runtime\\311\\python.exe .scripts\\cloud_install_8b.py --list-only

    # 正式安装（默认 Qwen3-8B，约 16.4 GB）
    ..\\..\\runtime\\311\\python.exe .scripts\\cloud_install_8b.py

    # 换模型 / 换目录 / 走镜像
    ..\\..\\runtime\\311\\python.exe .scripts\\cloud_install_8b.py --repo Qwen/Qwen3-8B --out /root/autodl-tmp/models/Qwen3-8B
    ..\\..\\runtime\\311\\python.exe .scripts\\cloud_install_8b.py --mirror
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from tqdm import tqdm

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

MODULE_ROOT = Path(__file__).resolve().parents[1]
def _autodl_dir() -> Path:
    """凭据目录：优先 labs/autoDL，退回模块根的 autoDL。"""
    for cand in (MODULE_ROOT / "labs" / "autoDL", MODULE_ROOT / "autoDL"):
        if cand.is_dir():
            return cand
    return MODULE_ROOT / "autoDL"


AUTODL_DIR = _autodl_dir()
REMOTE_SCRIPT = "/root/autodl-tmp/remote_fetch.py"


def find_password() -> Path | None:
    if not AUTODL_DIR.is_dir():
        return None
    for item in AUTODL_DIR.iterdir():
        if item.is_file() and item.name.lower() in (
                "密码.txt", "password.txt", "passwd.txt", "密码", "password"):
            return item
    for item in AUTODL_DIR.iterdir():
        if item.is_file() and ("密码" in item.name or "pass" in item.name.lower()):
            return item
    return None


def parse_login() -> tuple[str, int, str]:
    text = (AUTODL_DIR / "登录指令.txt").read_text(encoding="utf-8", errors="replace")
    host_match = re.search(r"(?:^|\s)([\w.\-]+@[\w.\-]+)", text)
    port_match = re.search(r"-p\s+(\d+)", text)
    if not host_match or not port_match:
        raise SystemExit("无法从 登录指令.txt 解析 host/port")
    user, host = host_match.group(1).split("@", 1)
    return user, int(port_match.group(1)), host


def human(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="Qwen/Qwen3-8B")
    ap.add_argument("--out", default="/root/autodl-tmp/models/Qwen3-8B")
    ap.add_argument("--mirror", action="store_true", help="远端走 hf-mirror.com")
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--python", default="/root/miniconda3/bin/python",
                    help="远端解释器路径")
    ap.add_argument("--no-turbo", action="store_true",
                    help="不 source /etc/network_turbo（默认会开：AutoDL 直连 HF 会超时）")
    args = ap.parse_args()

    import paramiko

    user, port, host = parse_login()
    pw_path = find_password()
    if not pw_path:
        raise SystemExit(f"找不到密码文件（放在 {AUTODL_DIR} 下）")
    password = pw_path.read_text(encoding="utf-8", errors="replace").strip()

    local_remote_script = MODULE_ROOT / ".scripts" / "remote_fetch.py"
    if not local_remote_script.is_file():
        raise SystemExit(f"缺少 {local_remote_script}")

    print(f"目标   : {user}@{host}:{port}")
    print(f"模型   : {args.repo}  ->  {args.out}")
    print(f"进度条 : 本地显示（远端逐块上报）")
    print("")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, port=port, username=user, password=password,
                   timeout=25, auth_timeout=25, banner_timeout=25,
                   allow_agent=False, look_for_keys=False)

    bar = None
    try:
        sftp = client.open_sftp()
        try:
            sftp.put(str(local_remote_script), REMOTE_SCRIPT)
        finally:
            sftp.close()
        print(f"已上传下载器：{REMOTE_SCRIPT}\n")

        inner = (f"{args.python} {REMOTE_SCRIPT} --repo {args.repo} "
                 f"--out {args.out}"
                 + (" --mirror" if args.mirror else "")
                 + (" --list-only" if args.list_only else ""))
        if args.no_turbo:
            cmd = f"{inner} 2>&1"
        else:
            # AutoDL 直连 huggingface.co 会超时；/etc/network_turbo 里配了代理，
            # source 之后 urllib 会自动走 http(s)_proxy 环境变量。
            cmd = f"bash -c 'source /etc/network_turbo >/dev/null 2>&1; {inner}' 2>&1"
        # 远端 stderr 也并进同一路，避免双流读取死锁
        channel = client.get_transport().open_session()
        channel.exec_command(cmd)
        stdout = channel.makefile("rb")

        files: list[tuple[str, int]] = []
        ok = False
        while True:
            raw = stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                continue
            parts = line.split("\t")
            tag = parts[0]

            if tag == "PROG":
                done, total = int(parts[1]), int(parts[2])
                name = parts[3] if len(parts) > 3 else ""
                if bar is None and total > 0:
                    bar = tqdm(total=total, unit="B", unit_scale=True,
                               unit_divisor=1024, dynamic_ncols=True,
                               bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} "
                                          "[{elapsed}<{remaining}, {rate_fmt}]")
                if bar is not None:
                    if done > bar.n:
                        bar.update(done - bar.n)
                    bar.set_description(f"{name[:38]:<38}", refresh=False)
            elif tag == "PLAN":
                count, total = int(parts[1]), int(parts[2])
                print(f"远端清单：{count} 个文件，共 {human(total)}（站点 {parts[3]}）")
            elif tag == "OUT":
                print(f"远端目录：{parts[1]}")
            elif tag == "FILE":
                files.append((parts[1], int(parts[2])))
                print(f"  - {parts[1]:<44} {human(int(parts[2])):>10}")
            elif tag == "FREE":
                free, need = int(parts[1]), int(parts[2])
                print(f"磁盘余量：{human(free)}（需要 {human(need)} + 2 GB）")
            elif tag == "NOSPACE":
                print("✗ 远端磁盘不够，先清点空间或换 --out")
            elif tag == "RETRY":
                print(f"  [重试 {parts[2]}/{parts[1]}] {parts[3][:80]}")
            elif tag == "FAIL":
                print(f"  ✗ 下载失败 {parts[1]}: {parts[2][:120]}")
            elif tag == "DONE":
                ok = True
                print("")
                print(f"✓ 完成：{human(int(parts[1]))} / {human(int(parts[2]))}  -> {parts[3]}")
            elif tag == "EMPTY":
                print("✗ 远端没匹配到文件")
            else:
                print(f"  {line}")

        if bar is not None:
            bar.close()
        code = channel.recv_exit_status()

        if args.list_only:
            print("\n（--list-only：未实际下载）")
            return 0

        if ok and code == 0:
            print("")
            print("下一步：有卡模式下验证能否被 transformers 加载")
            print(f"  {args.python} -c \"from transformers import AutoTokenizer; "
                  f"print(len(AutoTokenizer.from_pretrained('{args.out}')))\"")
            return 0
        print(f"\n✗ 未完成（远端退出码 {code}）。重跑本脚本会断点续传。")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
