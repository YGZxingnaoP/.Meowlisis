# -*- coding: utf-8 -*-
"""下载 27B FP8 模型（纯标准库，用全局 python 跑）。

特点
----
* **只用标准库**，不需要 pip 装 huggingface_hub / requests
* **断点续传**：写 `.part`，中断后重跑接着下
* **可指定目标目录**：`--dest`，方便你下完再移动到别处
* **镜像**：`--mirror` 走 hf-mirror.com（国内快）
* **进度**：显示 已下/总量、速度、剩余时间
* 已下完的文件会自动跳过（按大小校验）

用法（全局 python，目录自己定）
------------------------------
    python download_27b_fp8.py --list-only
    python download_27b_fp8.py --dest D:\\models\\Qwen3.5-27B-FP8
    python download_27b_fp8.py --dest E:\\models\\xxx --mirror
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ENDPOINTS = {"hf": "https://huggingface.co", "mirror": "https://hf-mirror.com"}

#: 默认仓库（可被 --repo 覆盖）
DEFAULT_REPO = "Qwen/Qwen3.5-27B-FP8"

#: 这些文件必须下（其余如 .md/.gitattributes 跳过）
KEEP_SUFFIX = (".safetensors", ".json", ".txt", ".model")
SKIP_NAMES = (".gitattributes", "README.md", "LICENSE", "LICENSE.txt")

CHUNK = 1 << 20          # 1 MiB
TIMEOUT = 60
RETRIES = 4


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


#: 镜像会拦 Python-urllib 的默认 UA（返回 403），所以伪装成浏览器
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def http_get(url: str, headers: dict | None = None):
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def head_size(url: str) -> int:
    try:
        with http_get(url) as r:      # 有些镜像不支持 HEAD，用 GET 读头
            return int(r.headers.get("Content-Length") or 0)
    except Exception:  # noqa: BLE001
        return 0


def list_files(endpoint: str, repo: str) -> list[tuple[str, int]]:
    url = f"{endpoint}/api/models/{repo}?blobs=true"
    with http_get(url) as r:
        data = json.loads(r.read().decode("utf-8"))

    out: list[tuple[str, int]] = []
    for item in data.get("siblings", []):
        name = item.get("rfilename") or ""
        if not name or name in SKIP_NAMES:
            continue
        if not name.endswith(KEEP_SUFFIX):
            continue
        size = int(item.get("size") or 0)
        if not size and isinstance(item.get("lfs"), dict):
            size = int(item["lfs"].get("size") or 0)
        if not size:                        # API 没给大小时用 HEAD 补
            size = head_size(f"{endpoint}/{repo}/resolve/main/{name}")
        if size:
            out.append((name, size))
    out.sort(key=lambda p: p[1])            # 小文件先下
    return out


def fetch(endpoint: str, repo: str, name: str, size: int, dest: str) -> bool:
    url = f"{endpoint}/{repo}/resolve/main/{name}"
    path = os.path.join(dest, name)
    os.makedirs(os.path.dirname(path) or dest, exist_ok=True)
    part = path + ".part"

    if os.path.isfile(path) and os.path.getsize(path) == size:
        print(f"  跳过 {name}（已完整）")
        return True

    have = os.path.getsize(part) if os.path.isfile(part) else 0
    if have > size:
        os.remove(part)
        have = 0
    if have:
        print(f"  续传 {name}（从 {human(have)}）")

    for attempt in range(1, RETRIES + 1):
        try:
            headers = {"Range": f"bytes={have}-"} if have else {}
            t0, last = time.time(), 0.0
            with http_get(url, headers) as r, open(part, "ab" if have else "wb") as fh:
                while True:
                    block = r.read(CHUNK)
                    if not block:
                        break
                    fh.write(block)
                    have += len(block)
                    now = time.time()
                    if now - last > 0.4:
                        last = now
                        speed = have / max(now - t0, 1e-6)
                        pct = have / size * 100 if size else 0
                        eta = (size - have) / speed if speed > 0 else 0
                        sys.stdout.write(
                            f"\r  {name[:34]:<34} {pct:5.1f}%  "
                            f"{human(have)}/{human(size)}  "
                            f"{human(speed)}/s  剩 {eta/60:.1f}分   ")
                        sys.stdout.flush()
            print()
            if size and os.path.getsize(part) != size:
                print(f"  ! {name} 大小不符（{os.path.getsize(part)} != {size}）")
            os.replace(part, path)
            return True
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            print(f"\n  重试 {attempt}/{RETRIES}：{type(e).__name__}: {e}")
            time.sleep(2 * attempt)
            have = os.path.getsize(part) if os.path.isfile(part) else 0
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--dest", default="")
    ap.add_argument("--mirror", action="store_true")
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--no-weights", action="store_true",
                    help="只下配置/词表等小文件，跳过 *.safetensors（先验证架构用）")
    args = ap.parse_args()

    endpoint = ENDPOINTS["mirror" if args.mirror else "hf"]
    print(f"仓库  : {args.repo}")
    print(f"站点  : {endpoint}")

    try:
        files = list_files(endpoint, args.repo)
    except urllib.error.HTTPError as e:
        print(f"\nHTTP {e.code}：仓库可能不存在，或该站点拒绝访问")
        print(f"  仓库: {args.repo}")
        print("  换一个试：--repo Qwen/Qwen3.5-27B")
        print("            --repo cyankiwi/Qwen3.8-27B-AWQ-FP8")
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"\n请求失败：{type(e).__name__}: {e}")
        print("  网络受限时先设代理：")
        print("    set HTTPS_PROXY=http://127.0.0.1:7890")
        return 2
    if args.no_weights:
        files = [(n, s) for n, s in files if not n.endswith(".safetensors")]

    if not files:
        print("没有匹配到文件。检查仓库名，或试试 --mirror")
        return 2
    total = sum(s for _, s in files)
    print(f"文件  : {len(files)} 个，共 {human(total)}\n")
    for name, size in files:
        print(f"  {name:<52} {human(size):>10}")

    if args.list_only:
        print("\n--list-only：未下载")
        return 0

    if not args.dest:
        print("\n必须指定 --dest（模型存哪）")
        return 2
    dest = os.path.abspath(args.dest)
    os.makedirs(dest, exist_ok=True)
    print(f"目标  : {dest}\n")

    st = os.statvfs(dest) if hasattr(os, "statvfs") else None
    if st:
        free = st.f_bavail * st.f_frsize
        print(f"磁盘  : 可用 {human(free)}，需要 {human(total)}")
        if free < total + (2 << 30):
            print("磁盘可能不够（需余量 2GB）")

    ok = 0
    for name, size in files:
        if fetch(endpoint, args.repo, name, size, dest):
            ok += 1
    print(f"\n完成 {ok}/{len(files)}")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    raise SystemExit(main())
