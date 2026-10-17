# -*- coding: utf-8 -*-
"""下载 Qwen3-0.6B 的 HuggingFace(safetensors) 版本。

为什么需要它
------------
`models/` 里现有的 `Qwen3-0.6B-Q8_0.gguf` 是给 llama.cpp 用的 GGUF 格式，
transformers 读不了。AsyncReasoning 需要 PyTorch/transformers，所以要另下一份
HF 格式的权重。

用法（在 .vendor/.MeowLLM 目录下运行）
--------------------------------------
    ..\\..\\runtime\\311\\python.exe .scripts\\download_qwen3_0.6b_hf.py --list-only
    ..\\..\\runtime\\311\\python.exe .scripts\\download_qwen3_0.6b_hf.py
    ..\\..\\runtime\\311\\python.exe .scripts\\download_qwen3_0.6b_hf.py --mirror
    ..\\..\\runtime\\311\\python.exe .scripts\\download_qwen3_0.6b_hf.py --out D:\\m\\Qwen3-0.6B

默认输出目录：.vendor/.MeowLLM/models/Qwen3-0.6B
预计体积：约 1449 MB（其中 model.safetensors 约 1434 MB）

特点
----
* 单条总进度条：已完成/总量、速度、剩余时间，按字节计
* 断点续传：中断后重跑会从 .part 接着下，不会从头再来
* 只下 transformers 需要的文件，跳过 README/LICENSE/其它格式权重
* 纯 requests + tqdm，不依赖 huggingface_hub 的缓存布局

不改动任何项目代码；产物只落在 --out 指定的目录里。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests
from tqdm import tqdm

# Windows 控制台默认 GBK，中文会花屏；能改就改成 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

REPO_ID = "Qwen/Qwen3-0.6B"

#: 两个站点提供同一套 API 与文件路径
ENDPOINTS = {
    "hf": "https://huggingface.co",
    "mirror": "https://hf-mirror.com",
}

#: transformers 加载所需的文件白名单
ALLOW_NAMES = {
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "model.safetensors.index.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "special_tokens_map.json",
    "added_tokens.json",
}

CHUNK = 1024 * 1024   # 1 MiB
TIMEOUT = 30          # 连接超时（秒）
RETRIES = 3


def human_bytes(num: float) -> str:
    """把字节数格式化成易读字符串。"""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载 Qwen3-0.6B 的 HF safetensors 权重")
    parser.add_argument("--repo", default=REPO_ID, help=f"HF 仓库 id（默认 {REPO_ID}）")
    parser.add_argument("--out", default=None,
                        help="输出目录（默认 .vendor/.MeowLLM/models/Qwen3-0.6B）")
    parser.add_argument("--mirror", action="store_true",
                        help="使用 hf-mirror.com（国内网络常用）")
    parser.add_argument("--all", action="store_true",
                        help="下载仓库内全部文件（默认只下 transformers 需要的）")
    parser.add_argument("--list-only", action="store_true",
                        help="只列出将下载的文件与体积，不实际下载")
    return parser.parse_args()


def default_out() -> Path:
    """本脚本位于 .vendor/.MeowLLM/.scripts/。

    parents[0] = .scripts
    parents[1] = .MeowLLM      <- 模块根，models/ 就在它下面
    """
    meowllm_root = Path(__file__).resolve().parents[1]
    return meowllm_root / "models" / "Qwen3-0.6B"


def head_size(session: requests.Session, endpoint: str, repo: str, name: str) -> int:
    """兜底：跟随重定向用 HEAD 取 Content-Length。"""
    try:
        resp = session.head(f"{endpoint}/{repo}/resolve/main/{name}",
                            timeout=15, allow_redirects=True)
        return int(resp.headers.get("Content-Length") or 0)
    except Exception:  # noqa: BLE001
        return 0


def list_remote_files(session: requests.Session, endpoint: str, repo: str,
                      take_all: bool) -> list[tuple[str, int]]:
    """列出文件及字节数。

    必须带 ?blobs=true，否则 HF 的 API 不返回 size；个别文件仍缺 size 时
    逐个 HEAD 补上。返回按体积降序，让进度条一开始就在动。
    """
    resp = session.get(f"{endpoint}/api/models/{repo}?blobs=true", timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()

    picked: list[tuple[str, int]] = []
    for item in payload.get("siblings", []):
        name = item.get("rfilename") or ""
        if not name:
            continue
        if not take_all and name not in ALLOW_NAMES:
            continue
        size = int(item.get("size") or 0)
        if not size and isinstance(item.get("lfs"), dict):
            size = int(item["lfs"].get("size") or 0)
        if not size:
            size = head_size(session, endpoint, repo, name)
        if size:
            picked.append((name, size))
        else:
            print(f"  跳过（取不到大小）：{name}")

    # 按体积**升序**：小文件（config.json / tokenizer）先落地。
    # 这样即使大权重还在下，安全闸门也能从 config.json 读到参数量并放行；
    # 反之按降序排会把 config.json 拖到最后，中间任何时刻都无法校验。
    picked.sort(key=lambda pair: (pair[1], pair[0]))
    return picked


def download_one(session: requests.Session, endpoint: str, repo: str,
                 name: str, size: int, dest_root: Path, bar: tqdm) -> None:
    """下载单个文件，支持断点续传；每收一块就推进总进度条。"""
    dest = dest_root / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    if dest.exists() and size and dest.stat().st_size == size:
        bar.update(size)          # 本地已完整，直接计入进度
        return

    already = part.stat().st_size if part.exists() else 0
    if already >= size:
        part.replace(dest)
        bar.update(size)
        return
    if already:
        bar.update(already)       # 续传：把已下部分计入进度

    bar.set_description(f"{name[:38]:<38}")

    for attempt in range(1, RETRIES + 1):
        headers = {"Range": f"bytes={already}-"} if already else {}
        try:
            with session.get(f"{endpoint}/{repo}/resolve/main/{name}",
                             headers=headers, stream=True,
                             timeout=(TIMEOUT, 120), allow_redirects=True) as resp:
                if resp.status_code == 416:      # 范围越界 = .part 已经完整
                    part.replace(dest)
                    return
                resp.raise_for_status()
                with open(part, "ab" if already else "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=CHUNK):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        bar.update(len(chunk))
            break
        except Exception as exc:  # noqa: BLE001
            if attempt >= RETRIES:
                raise
            print(f"\n  [重试 {attempt}/{RETRIES - 1}] {name}: {exc}")
            time.sleep(2 * attempt)
            already = part.stat().st_size if part.exists() else 0
            bar.update(min(already, size))

    part.replace(dest)


def main() -> int:
    args = parse_args()
    endpoint = ENDPOINTS["mirror" if args.mirror else "hf"]
    out_dir = Path(args.out).expanduser().resolve() if args.out else default_out()

    print("=" * 70)
    print(f"仓库 : {args.repo}")
    print(f"站点 : {endpoint}")
    print(f"输出 : {out_dir}")
    print("=" * 70)

    session = requests.Session()
    session.headers.update({"User-Agent": "meowllm-downloader/1.0"})

    try:
        files = list_remote_files(session, endpoint, args.repo, args.all)
    except Exception as exc:  # noqa: BLE001
        print(f"\n列出文件失败：{exc}")
        print("若是网络问题，加 --mirror 再试；仍失败请检查代理/防火墙。")
        return 2

    if not files:
        print("\n没有匹配到文件。加 --all 可下载仓库全部内容。")
        return 2

    total = sum(size for _, size in files)
    print(f"\n待下载 {len(files)} 个文件，共 {human_bytes(total)}")
    for name, size in files:
        print(f"  - {name:<34} {human_bytes(size):>10}")
    print("")

    if args.list_only:
        print("（--list-only：未实际下载）")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    fmt = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"
    with tqdm(total=total, unit="B", unit_scale=True, unit_divisor=1024,
              dynamic_ncols=True, mininterval=0.2, bar_format=fmt) as bar:
        for name, size in files:
            try:
                download_one(session, endpoint, args.repo, name, size, out_dir, bar)
            except Exception as exc:  # noqa: BLE001
                bar.close()
                print(f"\n下载失败：{name}\n  {exc}")
                print("重跑本脚本会从断点继续，不会从头再来。")
                return 3

    elapsed = time.time() - started
    missing = [n for n, _ in files if not (out_dir / n).exists()]
    print("")
    print("=" * 70)
    print(f"完成：{len(files)} 个文件，{human_bytes(total)}，用时 {elapsed:.1f}s，"
          f"平均 {human_bytes(total / max(elapsed, 1e-6))}/s")
    print(f"目录：{out_dir}")
    print("校验：全部就位" if not missing else f"校验：缺失 {missing}")
    print("=" * 70)
    print("")
    print("下一步：验证 transformers 能否加载（在 .vendor/.MeowLLM 下运行）")
    print('  ..\\..\\runtime\\311\\python.exe -c "from transformers import AutoTokenizer; '
          'print(len(AutoTokenizer.from_pretrained(r\'models/Qwen3-0.6B\')))"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
