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
    ... --model-dir models/Qwen3-8B   # 不传就用 config.yml 里的值
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
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

MODULE_ROOT = Path(__file__).resolve().parents[1]

# ---- 远端路径只有一个出处：labs/dmem_train/cloud_paths.py ----------------
# 云端就是本地这棵树换个根，所以 config.yml 里的相对路径（models/...）两边通用。
_TRAIN_DIR = MODULE_ROOT / "labs" / "dmem_train"
if str(_TRAIN_DIR) not in sys.path:
    sys.path.insert(0, str(_TRAIN_DIR))
import cloud_paths  # noqa: E402

REMOTE_ROOT = cloud_paths.remote_root()
REMOTE_LOG = "/root/autodl-tmp/meowllm_server.log"
REMOTE_PORT = 18100
#: 云端 backbone：相对模块根（与本地同一套相对路径）
DEFAULT_MODEL_REL = cloud_paths.DEFAULT_TRAIN_MODEL_REL


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
    ap.add_argument("--model-dir", default="",
                    help=f"后端 backbone（相对模块根的名字，默认 {DEFAULT_MODEL_REL}；"
                         f"会按 MEOWLLM_REMOTE_MODELS 翻译成云端实际路径）")
    ap.add_argument("--shared", action="store_true",
                    help="不隔离数据：状态/日志/δ-mem 都写云端主项目的 character/userinfo")
    ap.add_argument("--attach", action="store_true",
                    help="只开隧道，不动云端服务（云端已经在跑的时候用这个，省掉 90 秒重载）")
    ap.add_argument("--restart", action="store_true",
                    help="强制重启云端服务（默认：云端已健康就直接挂隧道）")
    ap.add_argument("--stop", action="store_true")
    args = ap.parse_args()

    client, user, host, port = connect()
    print(f"已连接 {user}@{host}:{port}")

    def run(cmd: str, timeout: int = 120) -> str:
        """跑一条远端命令并读回输出。

        **读超时绝不能让进程崩掉**：以前这里裸抛 TimeoutError，结果隧道还没开
        就退出了（远端 8B 明明活着，本地却连不上）。现在超时只返回已读到的部分。
        """
        chan = client.get_transport().open_session()
        chan.settimeout(timeout)
        try:
            chan.exec_command(cmd)
            chunks = []
            while True:
                if chan.recv_ready():
                    chunks.append(chan.recv(65536))
                    continue
                if chan.recv_stderr_ready():
                    chunks.append(chan.recv_stderr(65536))
                    continue
                if chan.exit_status_ready() and not chan.recv_ready():
                    break
                time.sleep(0.05)
            try:
                while chan.recv_ready():
                    chunks.append(chan.recv(65536))
                while chan.recv_stderr_ready():
                    chunks.append(chan.recv_stderr(65536))
            except Exception:  # noqa: BLE001
                pass
            return b"".join(chunks).decode("utf-8", "replace").strip()
        except Exception as exc:  # noqa: BLE001 - 超时/通道关闭都只当"没读到"
            return f"<<run timeout/error: {type(exc).__name__}>>"
        finally:
            try:
                chan.close()
            except Exception:  # noqa: BLE001
                pass

    def spawn(cmd: str) -> None:
        """fire-and-forget：起后台服务**不读通道**。

        为什么单独一个函数：`setsid nohup bash serve.sh &` 这种写法如果去读通道，
        paramiko 会一直等 stdout EOF，而后台进程继承了通道句柄 → 读超时 → 抛异常 →
        隧道没开成。这里只发命令、立刻关通道。
        """
        chan = client.get_transport().open_session()
        try:
            chan.exec_command(cmd + " < /dev/null")
            time.sleep(0.5)
        finally:
            try:
                chan.close()
            except Exception:  # noqa: BLE001
                pass

    if args.stop:
        print(run("pkill -f 'meowllm.server.app' ; echo stopped"))
        client.close()
        return 0

    def remote_healthy() -> bool:
        out = run(f"curl -s -m 3 -o /dev/null -w '%{{http_code}}' "
                  f"http://127.0.0.1:{REMOTE_PORT}/meowllm/control/health "
                  "2>/dev/null || echo 000", timeout=15)
        return out.strip().splitlines()[-1].strip() == "200" if out.strip() else False

    if args.attach:
        print("[cloud] --attach：不动云端服务，只开隧道")
        if not remote_healthy():
            print("[cloud] 警告：云端 18100 没有健康响应，隧道开着也连不上")
    elif not args.restart and remote_healthy():
        print("[cloud] 云端已经在跑（health 200），直接挂隧道；要重启用 --restart")
    else:
        # 1) 云端起服务（后台）
        #    不再用字符串拼一大串环境变量（那条路在遥控 shell 里挂过一次：整行解析失败，
        #    连重定向都没执行，日志停在旧内容，就绪判定还被旧日志骗了）。
        #    改成：写一个 serve.sh 到远端，再 setsid nohup bash 它。
        remote_model = cloud_paths.remote_model(args.model_dir or DEFAULT_MODEL_REL)
        lab_env = cloud_paths.lab_env(args.shared)
        env_lines = "\n".join(f'export {k}="{v}"' for k, v in sorted(lab_env.items()))
        serve_sh = f"""#!/bin/bash
# 由 .scripts/cloud_serve.py 生成：云端 MeowLLM 启动器（结构与本地一致，路径已转义）
set -u
cd "{REMOTE_ROOT}" || {{ echo "CD_FAIL"; exit 9; }}
export PATH="{cloud_paths.remote_bin_dir()}:/root/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONIOENCODING=utf-8
export MEOWLLM_ALLOW_LOCAL_MODEL=1
export MEOWLLM__ENGINE__KIND=dualstream
export MEOWLLM__SERVER__PORT={REMOTE_PORT}
export MEOWLLM__ENGINE__DUALSTREAM__MODEL_DIR="{remote_model}"
export MEOWLLM__SAFETY__MAX_LOCAL_MODEL_PARAMS_B=12
{env_lines}
echo "== boot $(date '+%F %T') =="
echo "cwd=$(pwd)  model=$MEOWLLM__ENGINE__DUALSTREAM__MODEL_DIR"
exec {cloud_paths.remote_python()} -m meowllm.server.app --log-level INFO
"""
        sftp = client.open_sftp()
        try:
            serve_path = f"{REMOTE_ROOT}/serve.sh"
            with sftp.open(serve_path, "w") as fh:
                fh.write(serve_sh)
            sftp.chmod(serve_path, 0o755)
            # 日志必须先清空：旧日志里有 "Uvicorn running"，会让就绪判定立刻假通过
            with sftp.open(REMOTE_LOG, "w"):
                pass
        finally:
            sftp.close()

        # 停旧进程：**必须连带历史上的启动器一起杀**。旧版本云端是用
        # `start_engine.py` / `run_meowllm.py` / `start_cloud_engine.py` 起的，
        # 它们的命令行里没有 "meowllm.server.app"，只 pkill 那个模式会留下一个
        # 抱着 16GB 显存的僵尸进程 —— 新进程随后必定 CUDA out of memory。
        # 模式里用 [m] 花括号技巧：否则 pkill 会匹配到**执行这条命令的 shell 自己**
        # （它的 cmdline 里也有这个字符串），把自己 kill 掉，后面的启动就不执行了。
        kill_pat = ("pkill -f '[m]eowllm.server.app' ; "
                    "pkill -f '[s]tart_engine\\.py' ; "
                    "pkill -f '[r]un_meowllm\\.py' ; "
                    "sleep 2")
        print(run(kill_pat + " ; echo killed"))
        # 显存没释放就再等一会儿（驱动回收有延迟）
        for _ in range(10):
            left = run("nvidia-smi --query-compute-apps=used_memory "
                       "--format=csv,noheader,nounits 2>/dev/null | "
                       "awk '{s+=$1} END {print s+0}'")
            if left.strip().splitlines()[-1].strip() in ("0", ""):
                break
            time.sleep(3)

        # fire-and-forget：不读通道，避免"后台进程占着通道 → 读超时 → 隧道没开成"
        spawn(f"cd {REMOTE_ROOT} && setsid nohup bash serve.sh > {REMOTE_LOG} 2>&1 &")
        print(f"[cloud] backbone: {remote_model}")
        print("[cloud] 等模型加载（8B 约 1-2 分钟）…")

        # 就绪判定：直接打远端 health（不再靠 grep 日志文本）
        ready = False
        for i in range(150):
            time.sleep(2)
            probe = run(
                f"curl -s -m 3 -o /dev/null -w '%{{http_code}}' "
                f"http://127.0.0.1:{REMOTE_PORT}/meowllm/control/health 2>/dev/null || echo 000")
            code = probe.strip().splitlines()[-1].strip() if probe.strip() else "000"
            if code == "200":
                print(f"[cloud] 已就绪（{i * 2 + 2}s，HTTP 200）")
                ready = True
                break
            if i % 10 == 9:
                tail = run(f"tail -3 {REMOTE_LOG}").replace("\n", " | ")
                print(f"[cloud] 仍在加载…（{i * 2 + 2}s）{tail[:160]}")
        if not ready:
            print("[cloud] 超时，日志尾部：")
            print(run(f"tail -40 {REMOTE_LOG}"))
            client.close()
            return 1

    # 2) 本地隧道
    transport = client.get_transport()

    # 本地端口可能已经被**上一次留下的隧道**占着（脚本被 Ctrl+C/kill 掉时，
    # forward_tunnel 里的 socket 有时比进程活得久）。先探一下，能用就直接复用，
    # 别再 bind 一次 —— 那会抛 WinError 10013，看起来像"启动失败"，其实一切正常。
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{args.local_port}/meowllm/control/health",
                timeout=3) as resp:
            if resp.status == 200:
                print(f"[tunnel] 127.0.0.1:{args.local_port} 已有隧道在转发"
                      f"（复用，不必再开）")
                print(f"[labs] 直接跑 labs\\run_lab.bat 即可")
                client.close()
                return 0
    except Exception:  # noqa: BLE001 - 没通就继续自己开
        pass

    print(f"\n[labs] 现在跑 labs\\run_lab.bat，它会探测 http://127.0.0.1:{args.local_port}")
    print("[labs] 或手动：node labs/server.js --meowllm "
          f"http://127.0.0.1:{args.local_port} --port 18700")
    print("[labs] Ctrl+C 断开隧道（云端服务不退出）\n")
    try:
        forward_tunnel(args.local_port, transport, "127.0.0.1", REMOTE_PORT)
    except PermissionError:
        print(f"\n[tunnel] 本地 {args.local_port} 端口被占用，且不是可用的隧道。"
              f"先关掉占它的程序（或换 --local-port 18101）")
        return 2
    except KeyboardInterrupt:
        print("\n[tunnel] 已断开")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
