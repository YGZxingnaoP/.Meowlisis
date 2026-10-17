# -*- coding: utf-8 -*-
"""远端下载器（纯标准库，跑在 AutoDL 上）。

设计要点
--------
* **只用 urllib**，不依赖 requests / huggingface_hub —— 云端 miniconda 可能什么都没装。
* **断点续传**：写 `.part`，用 HTTP Range 续；中断后重跑不会从头来。
* **机器可读进度**：每下载若干字节就往 stdout 打一行
      PROG\t<已下载字节>\t<总字节>\t<文件名>
  本地的编排脚本解析这行画进度条。最后打 DONE。
* 只下 transformers 需要的文件（config/tokenizer/权重分片），跳过 README/LICENSE/GGUF。

用法（云端）
------------
    python remote_fetch.py --repo Qwen/Qwen3-8B --out /root/autodl-tmp/models/Qwen3-8B
    python remote_fetch.py ... --mirror      # 走 hf-mirror.com
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

#: 明确需要的文件名
ALLOW_NAMES = {
    "config.json", "generation_config.json",
    "tokenizer.json", "tokenizer_config.json", "token_config.json",
    "vocab.json", "merges.txt", "special_tokens_map.json", "added_tokens.json",
}
#: 分片权重：model-00001-of-00004.safetensors
SHARD_RE = re.compile(r"^model-\d{5}-of-\d{5}\.safetensors$")
INDEX_RE = re.compile(r"^model\.safetensors\.index\.json$")

CHUNK = 1 << 20          # 1 MiB
REPORT_EVERY = 0.4       # 秒：进度行节流，避免刷屏
TIMEOUT = 60
RETRIES = 4


def emit_progress(done: int, total: int, name: str) -> None:
    sys.stdout.write(f"PROG\t{done}\t{total}\t{name}\n")
    sys.stdout.flush()


def http_get(url: str, headers: dict | None = None, timeout: int = TIMEOUT):
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout)


def head_size(endpoint: str, repo: str, name: str) -> int:
    """用 HEAD 取 Content-Length。

    为什么需要：经 AutoDL 的加速代理访问 HF API 时，`?blobs=true` 里的
    `size` / `lfs.size` 全是 None（实测），所以不能只靠 API 给大小。
    HEAD 会跟随重定向到 CDN，Content-Length 是准的。
    """
    req = urllib.request.Request(f"{endpoint}/{repo}/resolve/main/{name}",
                                 method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return int(resp.headers.get("Content-Length") or 0)
    except Exception:  # noqa: BLE001
        return 0


def list_files(endpoint: str, repo: str) -> list[tuple[str, int]]:
    """取文件清单与大小（API 缺大小时用 HEAD 补）。"""
    url = f"{endpoint}/api/models/{repo}?blobs=true"
    with http_get(url) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    picked: list[tuple[str, int]] = []
    for item in payload.get("siblings", []):
        name = item.get("rfilename") or ""
        if not name:
            continue
        keep = (name in ALLOW_NAMES or bool(SHARD_RE.match(name))
                or bool(INDEX_RE.match(name)) or name.endswith(".safetensors"))
        if not keep:
            continue
        size = int(item.get("size") or 0)
        if not size and isinstance(item.get("lfs"), dict):
            size = int(item["lfs"].get("size") or 0)
        if not size:
            size = head_size(endpoint, repo, name)
        if not size:
            sys.stderr.write(f"SKIP\t{name}\t取不到大小\n")
            continue
        picked.append((name, size))
    picked.sort(key=lambda p: (p[1], p[0]))     # 小文件先落地，闸门能早放行
    return picked


def fetch_one(endpoint: str, repo: str, name: str, size: int, out_dir: str,
              counter: dict, total_all: int) -> None:
    """下载单个文件，支持续传，边下边报进度。"""
    url = f"{endpoint}/{repo}/resolve/main/{name}"
    dest = os.path.join(out_dir, name)
    os.makedirs(os.path.dirname(dest) or out_dir, exist_ok=True)
    part = dest + ".part"

    if os.path.isfile(dest) and size and os.path.getsize(dest) == size:
        counter["done"] += size
        emit_progress(counter["done"], total_all, name)
        return

    have = os.path.getsize(part) if os.path.isfile(part) else 0
    if have > size:
        have = 0
        os.remove(part)

    for attempt in range(1, RETRIES + 1):
        try:
            headers = {"Range": f"bytes={have}-"} if have else {}
            with http_get(url, headers) as resp:
                mode = "ab" if have else "wb"
                last = 0.0
                with open(part, mode) as fh:
                    while True:
                        block = resp.read(CHUNK)
                        if not block:
                            break
                        fh.write(block)
                        have += len(block)
                        counter["done"] += len(block)
                        now = time.time()
                        if now - last > REPORT_EVERY:
                            emit_progress(counter["done"], total_all, name)
                            last = now
            emit_progress(counter["done"], total_all, name)
            os.replace(part, dest)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            if attempt >= RETRIES:
                sys.stderr.write(f"FAIL\t{name}\t{type(exc).__name__}: {exc}\n")
                sys.stderr.flush()
                raise SystemExit(4)
            sys.stderr.write(f"RETRY\t{name}\t{attempt}\t{exc}\n")
            sys.stderr.flush()
            time.sleep(2 * attempt)
            have = os.path.getsize(part) if os.path.isfile(part) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="Qwen/Qwen3-8B")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mirror", action="store_true")
    ap.add_argument("--list-only", action="store_true")
    args = ap.parse_args()

    endpoint = ENDPOINTS["mirror" if args.mirror else "hf"]
    out_dir = os.path.abspath(args.out)

    files = list_files(endpoint, args.repo)
    if not files:
        sys.stderr.write("EMPTY\t没有匹配到任何文件\n")
        return 2
    total = sum(s for _, s in files)

    sys.stderr.write(f"PLAN\t{len(files)}\t{total}\t{endpoint}\n")
    sys.stderr.write(f"OUT\t{out_dir}\n")
    for name, size in files:
        sys.stderr.write(f"FILE\t{name}\t{size}\n")
    sys.stderr.flush()

    if args.list_only:
        return 0

    # 磁盘余量检查（留 2 GB 余量）
    st = os.statvfs(out_dir if os.path.isdir(out_dir) else os.path.dirname(out_dir) or "/")
    free = st.f_bavail * st.f_frsize
    sys.stderr.write(f"FREE\t{free}\t{total}\n")
    sys.stderr.flush()
    if free < total + 2 * (1 << 30):
        sys.stderr.write("NOSPACE\t磁盘余量不足（需要总量 + 2GB）\n")
        return 3

    os.makedirs(out_dir, exist_ok=True)
    counter = {"done": 0}
    for name, size in files:
        fetch_one(endpoint, args.repo, name, size, out_dir, counter, total)

    sys.stdout.write(f"DONE\t{counter['done']}\t{total}\t{out_dir}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
