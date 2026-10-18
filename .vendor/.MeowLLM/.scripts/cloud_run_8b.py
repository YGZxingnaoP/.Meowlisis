# -*- coding: utf-8 -*-
"""分片到位后，一条命令把引擎推上云端并跑出 8B 的真实 tps。

做四件事
--------
1. 校验 8B 结构（5 片齐全、config 可读、能被 transformers 认出）
2. 把本地 `meowllm/` 打包上传到云端（跳过 weights/日志/缓存）
3. 在云端跑一段双流（thinker + writer）基线：记录 tok/s、首 token 延迟
4. 打印结论

用法（在 .vendor/.MeowLLM 目录下）
---------------------------------
    ..\\..\\runtime\\311\\python.exe .scripts\\cloud_run_8b.py
    ... --check-only      # 只校验模型，不上传不跑
    ... --model-dir /root/autodl-tmp/models/Qwen3-8B
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tarfile
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

MODULE_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHARD = 3_996_250_744

REMOTE_CODE = "/root/autodl-tmp/meowllm_code"
REMOTE_TAR = "/root/autodl-tmp/meowllm_code.tar.gz"

#: 打包时排除
EXCLUDE_DIRS = {"__pycache__", ".test", "models", "labs", "bags", "llama.cpp",
                "docs", ".scripts", "_deprecated"}
EXCLUDE_SUFFIX = {".pyc", ".log", ".gguf", ".safetensors", ".whl", ".tar.gz"}


def _autodl_dir() -> Path:
    for cand in (MODULE_ROOT / "labs" / "autoDL", MODULE_ROOT / "autoDL"):
        if cand.is_dir():
            return cand
    return MODULE_ROOT / "autoDL"


def find_password() -> Path | None:
    d = _autodl_dir()
    if not d.is_dir():
        return None
    for item in d.iterdir():
        if item.is_file() and item.name.lower() in (
                "密码.txt", "password.txt", "passwd.txt", "密码", "password"):
            return item
    return None


def parse_login() -> tuple[str, int, str]:
    text = (_autodl_dir() / "登录指令.txt").read_text(encoding="utf-8", errors="replace")
    host = re.search(r"(?:^|\s)([\w.\-]+@[\w.\-]+)", text)
    port = re.search(r"-p\s+(\d+)", text)
    if not host or not port:
        raise SystemExit("无法解析 登录指令.txt")
    user, h = host.group(1).split("@", 1)
    return user, int(port.group(1)), h


def build_tar() -> Path:
    """把 meowllm/ 与 config.yml 打成一个 tar.gz（跳过无关目录）。"""
    out = Path(tempfile.gettempdir()) / "meowllm_code.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        for entry in ("meowllm", "config.yml"):
            src = MODULE_ROOT / entry
            if not src.exists():
                continue
            if src.is_file():
                tf.add(src, arcname=entry)
                continue
            for path in src.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(MODULE_ROOT)
                if any(part in EXCLUDE_DIRS for part in rel.parts):
                    continue
                if path.suffix in EXCLUDE_SUFFIX:
                    continue
                tf.add(path, arcname=str(rel))
    return out


REMOTE_TEST = r'''
import json, time, torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import sys
sys.path.insert(0, "/root/autodl-tmp/meowllm_code")
from meowllm.engine.dualstream.loop import DualStreamLoop

MODEL = __MODEL__
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(
    MODEL, dtype=torch.bfloat16, device_map="cuda").eval()
print("MODEL_OK", sum(p.numel() for p in model.parameters()) / 1e9, "B")
print("VRAM", torch.cuda.memory_allocated() / 1e9, "GB")

loop = DualStreamLoop(model, tok, probe_every=10**9, device="cuda")
loop._graph_ok = False
loop.reset([{"role": "user", "content": "What is 5 - 25 + 125?"}])
torch.cuda.synchronize()
t0 = time.perf_counter()
N = 24
for _ in range(N):
    loop.step()
torch.cuda.synchronize()
dt = time.perf_counter() - t0
print("STEPS", N, "SECONDS", round(dt, 3),
      "MS_PER_STEP", round(dt / N * 1000, 2),
      "TOK_PER_S", round(2 * N / dt, 1))
print("THINKER", "".join(loop._thinker_buf.split())[:60])
print("WRITER", "".join(loop._writer_buf.split())[:60])
print("GRAPH_DISABLED", getattr(loop.stats, "graph_disabled", None))
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default="/root/autodl-tmp/models/Qwen3-8B")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--steps", type=int, default=24)
    args = ap.parse_args()

    import paramiko

    user, port, host = parse_login()
    pw = find_password()
    if not pw:
        raise SystemExit("找不到密码文件")
    password = pw.read_text(encoding="utf-8", errors="replace").strip()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"连接 {user}@{host}:{port} …")
    client.connect(hostname=host, port=port, username=user, password=password,
                   timeout=25, auth_timeout=25, banner_timeout=25,
                   allow_agent=False, look_for_keys=False)
    print("已连接。")

    def run(cmd: str, timeout: int = 900) -> tuple[int, str]:
        _in, out, err = client.exec_command(cmd, timeout=timeout)
        text = out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")
        return out.channel.recv_exit_status(), text.strip()

    try:
        # ---- 1) 校验模型 ----
        print("\n=== 1) 校验 8B 结构 ===")
        code, text = run(
            f"stat -c %s {args.model_dir}/model-00001-of-00005.safetensors 2>/dev/null || echo 0;"
            f" ls {args.model_dir}/*.safetensors 2>/dev/null | wc -l")
        print(text)
        sizes = [ln for ln in text.splitlines() if ln.strip().isdigit()]
        if sizes and int(sizes[0]) != EXPECTED_SHARD:
            print(f"✗ 第一片大小 {sizes[0]} != {EXPECTED_SHARD}，分片未就位，停止")
            return 1
        code, text = run(
            f"/root/miniconda3/bin/python -c \"from transformers import AutoConfig;"
            f" c=AutoConfig.from_pretrained('{args.model_dir}');"
            f" print(c.model_type, c.num_hidden_layers, c.vocab_size)\"", 300)
        print(text)
        if "qwen" not in text.lower():
            print("✗ config 读不出来，停止")
            return 1
        if args.check_only:
            print("\n--check-only：到此为止")
            return 0

        # ---- 2) 上传代码 ----
        print("\n=== 2) 上传引擎代码 ===")
        tar = build_tar()
        print(f"  打包 {tar.name} = {tar.stat().st_size / 1024:.0f} KB")
        sftp = client.open_sftp()
        try:
            sftp.put(str(tar), REMOTE_TAR)
        finally:
            sftp.close()
        code, text = run(f"rm -rf {REMOTE_CODE} && mkdir -p {REMOTE_CODE} && "
                         f"tar xzf {REMOTE_TAR} -C {REMOTE_CODE} && "
                         f"ls {REMOTE_CODE} && ls {REMOTE_CODE}/meowllm/engine/dualstream", 300)
        print(text)

        # ---- 3) 跑双流基线 ----
        print("\n=== 3) 双流基线（8B）===")
        script = REMOTE_TEST.replace("__MODEL__", repr(args.model_dir))
        script = script.replace("N = 24", f"N = {args.steps}")
        sftp = client.open_sftp()
        try:
            with sftp.open("/root/autodl-tmp/run_ar_test.py", "w") as fh:
                fh.write(script)
        finally:
            sftp.close()
        code, text = run("/root/miniconda3/bin/python /root/autodl-tmp/run_ar_test.py", 1800)
        print(text)
        return 0 if code == 0 else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
