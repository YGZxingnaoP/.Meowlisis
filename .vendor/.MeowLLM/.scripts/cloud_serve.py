# -*- coding: utf-8 -*-
"""把云端 8B 通过 SSH 隧道接到本地 labs：一条命令完成。

做三件事：
1. 连上 AutoDL，在云端后台启动 MeowLLM 服务（绑定 127.0.0.1:18100）
2. 在**本地** 127.0.0.1:18100 开一个转发到云端 18100 的隧道
3. 保持前台运行；此时直接跑 labs\\run_lab.bat，它探测到 18100 有健康实例就复用

用法
----
    ..\\..\\runtime\\311\\python.exe .scripts\\cloud_serve.py
    ... --local-port 18101        # 本地端口被占时换一个
    ... --model-dir /root/autodl-tmp/models/Qwen3-8B
    ... --stop                    # 只停掉云端服务

前台最后会打印 labs 该连哪个地址。Ctrl+C 断开隧道（云端服务继续跑）。
"""

from __future__ import annotations

import argparse
import re
import select
import socket
import sys
import threading
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

MODULE_ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/root/autodl-tmp/meowllm_code"
REMOTE_LOG = "/root/autodl-tmp/meowllm_server.log"
REMOTE_PORT = 18100


def _autodl_dir() -> Path:
    for cand in (MODULE_ROOT / "labs" / "autoDL", MODULE_ROOT / "autoDL"):
        if cand.is_dir():
            return cand
    return MODULE_ROOT / "autoDL"


def connect():
    import paramiko

    d = _autodl_dir()
    text = (d / "登录指令.txt").read_text(encoding="utf-8", errors="replace")
    host = re.search(r"(?:^|\s)([\w.\-]+@[\w.\-]+)", text)
    port = re.search(r"-p\s+(\d+)", text)
    if not host or not port:
        raise SystemExit("无法解析 登录指令.txt")
    user, h = host.group(1).split("@", 1)
    pw = None
    for item in d.iterdir():
        if item.is_file() and item.name.lower() in (
                "密码.txt", "password.txt", "passwd.txt", "密码", "password"):
            pw = item.read_text(encoding="utf-8", errors="replace").strip()
            break
    if not pw:
        raise SystemExit("找不到密码文件")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=h, port=int(port.group(1)), username=user, password=pw,
                   timeout=25, auth_timeout=25, banner_timeout=25,
                   allow_agent=False, look_for_keys=False)
    return client, user, h, int(port.group(1))


def forward_tunnel(local_port: int, transport, remote_host: str, remote_port: int) -> None:
    """把本地端口的连接转发到远端的 remote_host:remote_port（走已建立的 ssh 连接）。"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", local_port))
    server.listen(16)
    print(f"[tunnel] 127.0.0.1:{local_port} -> {remote_host}:{remote_port}", flush=True)

    def handle(channel, sock):
        try:
            while True:
                r, _, _ = select.select([sock, channel], [], [])
                if sock in r:
                    data = sock.recv(4096)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in r:
                    data = channel.recv(4096)
                    if not data:
                        break
                    sock.sendall(data)
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                channel.close()
            except Exception:  # noqa: BLE001
                pass
            sock.close()

    while True:
        sock, _addr = server.accept()
        try:
            channel = transport.open_channel("direct-tcpip",
                                             (remote_host, remote_port),
                                             sock.getpeername())
        except Exception as exc:  # noqa: BLE001
            print(f"[tunnel] 打开通道失败: {exc}", flush=True)
            sock.close()
            continue
        threading.Thread(target=handle, args=(channel, sock), daemon=True).start()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-port", type=int, default=REMOTE_PORT)
    ap.add_argument("--model-dir", default="/root/autodl-tmp/models/Qwen3-8B")
    ap.add_argument("--stop", action="store_true")
    args = ap.parse_args()

    client, user, host, port = connect()
    print(f"已连接 {user}@{host}:{port}")

    def run(cmd: str, timeout: int = 120) -> str:
        _i, out, err = client.exec_command(cmd, timeout=timeout)
        return (out.read() + err.read()).decode("utf-8", "replace").strip()

    if args.stop:
        print(run(f"pkill -f '[m]eowllm.server.app' ; echo stopped"))
        client.close()
        return 0

    # 1) 云端起服务（后台），改用云端模型目录
    cfg_patch = (
        f"cd {REMOTE_ROOT} && "
        f"MEOWLLM_ALLOW_LOCAL_MODEL=1 "
        f"MEOWLLM__ENGINE__KIND=dualstream "
        f"MEOWLLM__SERVER__PORT={REMOTE_PORT} "
        f"MEOWLLM__ENGINE__DUALSTREAM__MODEL_DIR={args.model_dir} "
        f"nohup /root/miniconda3/bin/python -m meowllm.server.app --log-level INFO "
        f"> {REMOTE_LOG} 2>&1 & echo started"
    )
    print(run(f"pkill -f '[m]eowllm.server.app' ; sleep 1 ; " + cfg_patch))
    print("[cloud] 等模型加载（8B 约 1-2 分钟）…")
    for i in range(90):
        time.sleep(2)
        txt = run(f"grep -c 'Uvicorn running' {REMOTE_LOG} 2>/dev/null || echo 0")
        if txt.strip().splitlines()[-1].strip() not in ("0", ""):
            print(f"[cloud] 已就绪（{i * 2 + 2}s）")
            break
    else:
        print("[cloud] 超时，日志尾部：")
        print(run(f"tail -20 {REMOTE_LOG}"))
        client.close()
        return 1

    # 2) 本地隧道
    transport = client.get_transport()
    print(f"\n[labs] 现在跑 labs\\run_lab.bat，它会探测 http://127.0.0.1:{args.local_port}")
    print("[labs] 或手动：node labs/server.js --meowllm "
          f"http://127.0.0.1:{args.local_port} --port 18700")
    print("[labs] Ctrl+C 断开隧道（云端服务不退出）\n")
    try:
        forward_tunnel(args.local_port, transport, "127.0.0.1", REMOTE_PORT)
    except KeyboardInterrupt:
        print("\n[tunnel] 已断开")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
