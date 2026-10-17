# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_PORT = 18100
DEFAULT_SPAN = 9
LAB_PORT = 18700


def health(port: int, timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/meowllm/control/health",
                timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def find_live(base: int, span: int = DEFAULT_SPAN) -> tuple[int, dict] | None:
    for offset in range(span):
        port = base + offset
        data = health(port)
        if data is not None:
            return port, data
    return None


def find_python() -> str:
    env = os.environ.get("MEOWLLM_PYTHON")
    if env and Path(env).is_file():
        return env
    cand = ROOT.parent.parent / "runtime" / "311" / "python.exe"
    if cand.is_file():
        return str(cand)
    return sys.executable


def find_node() -> str:
    env = os.environ.get("MEOWLLM_NODE")
    if env and Path(env).is_file():
        return env
    try:
        out = subprocess.run(["where", "node"], capture_output=True, text=True,
                             timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass
    roots = [Path("D:/Nodejs"), Path("C:/Program Files/nodejs"),
             Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "nodejs"]
    for root in roots:
        if not root.is_dir():
            continue
        for exe in sorted(root.glob("*/node.exe")) + sorted(root.glob("node.exe")):
            if exe.is_file():
                return str(exe)
    return "node"


def start_engine(py: str, port: int, engine: str | None) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["MEOWLLM_ALLOW_LOCAL_MODEL"] = "1"
    if engine:
        env["MEOWLLM__ENGINE__KIND"] = engine
    env["MEOWLLM__SERVER__PORT"] = str(port)
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_CONSOLE
    print(f"[lab] 启动 MeowLLM（engine={engine or 'config.yml'}，端口 {port}）…")
    return subprocess.Popen([py, "-m", "meowllm.server.app", "--log-level", "INFO"],
                            cwd=str(ROOT), env=env, creationflags=flags)


def wait_ready(base: int, proc: subprocess.Popen | None = None,
               timeout: float = 240.0, span: int = DEFAULT_SPAN) -> tuple[int, dict] | None:
    started = time.time()
    sys.stdout.write("[lab] 等模型就绪")
    sys.stdout.flush()
    while time.time() - started < timeout:
        hit = find_live(base, span)
        if hit is not None:
            print(f"\n[lab] 就绪（{time.time() - started:.0f}s，端口 {hit[0]}）")
            return hit
        if proc is not None and proc.poll() is not None:
            print(f"\n[lab] MeowLLM 进程已退出（exit={proc.returncode}），看它的窗口日志")
            return None
        sys.stdout.write(".")
        sys.stdout.flush()
        time.sleep(2)
    print("\n[lab] 超时：MeowLLM 没起来，看那个新开的控制台窗口")
    return None


def start_lab(port: int, lab_port: int) -> subprocess.Popen:
    url = f"http://127.0.0.1:{port}"
    node = find_node()
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_CONSOLE
    print(f"[lab] 启动实验台 http://127.0.0.1:{lab_port}（node={node}）")
    return subprocess.Popen(
        [node, "server.js", "--meowllm", url, "--port", str(lab_port)],
        cwd=str(HERE), creationflags=flags)


def _start_cloud(port: int) -> bool:
    import importlib.util
    import threading

    path = ROOT / ".scripts" / "cloud_serve.py"
    if not path.is_file():
        print("[cloud] 找不到 .scripts/cloud_serve.py")
        return False
    try:
        spec = importlib.util.spec_from_file_location("cloud_serve", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        print(f"[cloud] 加载 cloud_serve 失败：{exc}")
        return False

    try:
        client, user, host, sshport = mod.connect()
    except SystemExit as exc:
        print(f"[cloud] 凭据问题：{exc}")
        return False
    except Exception as exc:
        print(f"[cloud] 连接失败：{type(exc).__name__}: {exc}")
        return False
    print(f"[cloud] 已连接 {user}@{host}:{sshport}")

    remote_cmd = (
        f"cd {mod.REMOTE_ROOT} && "
        f"MEOWLLM_ALLOW_LOCAL_MODEL=1 MEOWLLM__ENGINE__KIND=dualstream "
        f"MEOWLLM__SERVER__PORT={mod.REMOTE_PORT} "
        f"MEOWLLM__SAFETY__MAX_LOCAL_MODEL_PARAMS_B=12 "
        f"MEOWLLM__ENGINE__DUALSTREAM__MODEL_DIR=/root/autodl-tmp/models/Qwen3-8B "
        f"nohup setsid /root/miniconda3/bin/python -m meowllm.server.app "
        f"> /root/autodl-tmp/srv{mod.REMOTE_PORT}.log 2>&1 & echo ok"
    )
    try:
        client.exec_command(remote_cmd)
    except Exception as exc:
        print(f"[cloud] 启动远端服务失败：{exc}")
        return False

    threading.Thread(
        target=mod.forward_tunnel,
        args=(port, client.get_transport(), "127.0.0.1", mod.REMOTE_PORT),
        daemon=True).start()
    print(f"[cloud] 隧道已开：127.0.0.1:{port} -> 云端 {mod.REMOTE_PORT}（8B 加载中）")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default=None, help="dualstream | stub")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--lab-port", type=int, default=LAB_PORT)
    ap.add_argument("--nobrowser", action="store_true")
    ap.add_argument("--cloud", action="store_true",
                    help="本地没有实例时尝试连云端 8B（默认只起本地）")
    ap.add_argument("--local", action="store_true",
                    help="等价于不加 --cloud，保留兼容")
    args = ap.parse_args()

    py = find_python()
    live_port = args.port

    hit = find_live(args.port)
    if hit is not None:
        live_port, data = hit
        eng = (data.get("engine") or {}).get("engine", "?")
        print(f"[lab] 复用已在运行的 MeowLLM（engine={eng}，端口 {live_port}）")
        engine_proc = None
    elif args.cloud and not args.local:
        engine_proc = None
        if _start_cloud(args.port):
            hit = wait_ready(args.port, timeout=300)
            if hit is None:
                print("[cloud] 云端没起来，退回本地")
            else:
                live_port = hit[0]
        if hit is None:
            engine_proc = start_engine(py, args.port, args.engine)
            hit = wait_ready(args.port, proc=engine_proc)
            if hit is None:
                return 1
            live_port = hit[0]
    else:
        engine_proc = start_engine(py, args.port, args.engine)
        hit = wait_ready(args.port, proc=engine_proc)
        if hit is None:
            return 1
        live_port = hit[0]

    lab = start_lab(live_port, args.lab_port)
    time.sleep(2.5)

    if not args.nobrowser:
        try:
            webbrowser.open(f"http://127.0.0.1:{args.lab_port}")
        except Exception:
            pass

    print("")
    print(f"[lab] 页面：http://127.0.0.1:{args.lab_port}（MeowLLM {live_port}）")
    if engine_proc is not None:
        print(f"[lab] MeowLLM 在另一个窗口里（pid {engine_proc.pid}），关窗口即停")
    else:
        print("[lab] MeowLLM 是复用的，不会随实验台退出")
    print("[lab] 按 Ctrl+C 退出实验台（node pid %d）" % lab.pid)
    try:
        lab.wait()
    except KeyboardInterrupt:
        lab.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
