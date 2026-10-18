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


SSH_LINE_RE = re.compile(r"(?:(?P<user>[\w.\-]+)@)?(?P<host>[\w.\-]+)")


def parse_ssh_line(text: str) -> dict:
    """解析 AutoDL 那种登录指令，也接受裸 `user@host`。

    支持：
        ssh -p 49229 root@connect.westb.seetacloud.com
        root@connect.westb.seetacloud.com -p 49229
        root@1.2.3.4
    """
    raw = str(text or "").strip().strip('"').strip("'")
    if not raw:
        raise SystemExit("SSH 指令为空")
    port_m = re.search(r"-p\s*(\d{1,5})", raw)
    user, host = None, None
    for tok in raw.replace("'", " ").replace('"', " ").split():
        low = tok.lower()
        if low in ("ssh", "scp", "sftp") or tok.startswith("-") or tok.isdigit():
            continue
        if "@" in tok:
            u, h = tok.split("@", 1)
            if h and not h.startswith("-"):
                user, host = (u or "root"), h
                break
        if host is None and re.fullmatch(r"[\w.\-]+", tok) and "." in tok:
            host = tok
    if not host:
        raise SystemExit(f"无法从这段里认出 user@host：{raw!r}")
    return {"user": user or "root", "host": host,
            "port": int(port_m.group(1)) if port_m else 22}


def _read_saved_creds() -> tuple[dict, str] | None:
    """读 `labs/autoDL/` 里上一次保存的凭据；没有或不完整就返回 None。"""
    d = _autodl_dir()
    line_file = d / "登录指令.txt"
    if not line_file.is_file():
        return None
    try:
        text = line_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    pw = None
    try:
        for item in d.iterdir():
            if item.is_file() and item.name.lower() in (
                    "密码.txt", "password.txt", "passwd.txt", "密码", "password"):
                pw = item.read_text(encoding="utf-8", errors="replace").strip()
                break
    except OSError:
        pass
    if not pw:
        return None
    try:
        return parse_ssh_line(text), pw
    except SystemExit:
        return None


def _save_creds(creds: dict, password: str) -> None:
    d = _autodl_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "登录指令.txt").write_text(
        f"ssh -p {creds['port']} {creds['user']}@{creds['host']}\n", encoding="utf-8")
    (d / "密码.txt").write_text(str(password) + "\n", encoding="utf-8")
    print(f"[cred] 已保存到 {d}（.gitignore 已排除，不会入库）")


def _ask_creds() -> tuple[dict, str]:
    """交互式要凭据：粘贴 ssh 行 + 输入密码（不回显）。"""
    import getpass

    if not sys.stdin.isatty():
        raise SystemExit(
            "没有可用的云端凭据，且当前不是交互终端。\n"
            "  做法一：先跑一次  python .scripts\\cloud_serve.py --ask --save\n"
            "  做法二：用 --ssh \"ssh -p 端口 root@主机\" --password <密码>")
    print()
    print("没有可用的云端凭据。粘贴 AutoDL 的登录指令（含 -p 和 user@host）：")
    print("  例：ssh -p 49229 root@connect.westb.seetacloud.com")
    try:
        line = input("ssh> ").strip()
        creds = parse_ssh_line(line)
        pw = getpass.getpass(
            f"{creds['user']}@{creds['host']}:{creds['port']} 的密码（不回显）> ").strip()
    except (EOFError, KeyboardInterrupt) as exc:
        raise SystemExit(
            "没有读到输入（非交互环境）。\n"
            "  做法一：在真实终端里双击 start_cloud.bat\n"
            "  做法二：用 --ssh \"ssh -p 端口 root@主机\" --password <密码>") from exc
    if not pw:
        raise SystemExit("密码为空")
    print(f"[cred] 目标 {creds['user']}@{creds['host']}:{creds['port']}")
    return creds, pw


def connect(creds: dict | None = None, password: str | None = None,
            ask: bool = False, save: bool = True):
    """连上云端。凭据优先级：显式参数 > --ask 交互 > labs/autoDL/ 里保存的。

    换卡之后最常见的情况是**旧凭据还在但已经失效**。所以这里做了自动兜底：
    用保存的凭据连不上、且当前是交互终端 → 直接让你重输一次（并覆盖保存），
    而不是丢一句报错让人自己加 --ask。
    """
    import paramiko

    interactive = False
    if creds is None:
        if ask:
            creds, password = _ask_creds()
            interactive = True
        else:
            saved = _read_saved_creds()
            if saved is not None:
                creds, password = saved
            else:
                creds, password = _ask_creds()
                interactive = True
    if save and password and interactive:
        _save_creds(creds, password)

    def _dial():
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=creds["host"], port=int(creds["port"]),
                       username=creds["user"], password=password,
                       timeout=25, auth_timeout=25, banner_timeout=25,
                       allow_agent=False, look_for_keys=False)
        return client

    try:
        client = _dial()
    except Exception as exc:  # noqa: BLE001
        if interactive or ask or not sys.stdin.isatty():
            raise SystemExit(
                f"连不上 {creds['user']}@{creds['host']}:{creds['port']}："
                f"{type(exc).__name__}: {exc}\n"
                f"（换了实例之后 host/port/密码都会变，用 --ask 重新输入）") from exc
        print(f"\n[cred] 保存的凭据连不上（{type(exc).__name__}）。"
              f"是不是换实例了？重新输入一次：")
        creds, password = _ask_creds()
        if save:
            _save_creds(creds, password)
        try:
            client = _dial()
        except Exception as exc2:  # noqa: BLE001
            raise SystemExit(
                f"还是连不上 {creds['user']}@{creds['host']}:{creds['port']}："
                f"{type(exc2).__name__}: {exc2}") from exc2
    return client, creds["user"], creds["host"], int(creds["port"])


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
    ap = argparse.ArgumentParser(
        description="把云端 MeowLLM 接到本地（换实例后推荐：cloud_serve.py --ask --save）")
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
    ap.add_argument("--ask", action="store_true",
                    help="强制交互输入 ssh 指令 + 密码（换卡后旧凭据失效时用这个）")
    ap.add_argument("--save", action="store_true",
                    help="把这次输入的凭据存到 labs/autoDL/，下次直接回车即可")
    ap.add_argument("--ssh", default="",
                    help="直接给登录指令，如 \"ssh -p 49229 root@connect.westb.seetacloud.com\"")
    ap.add_argument("--password", default="",
                    help="直接给密码（会留在命令历史里，不推荐；优先交互输入）")
    ap.add_argument("--preflight", action="store_true",
                    help="只做云端体检（不启动服务）：python/torch/模型/权重/代码/显存")
    ap.add_argument("--setup", action="store_true",
                    help="体检不通过时在云端装依赖 + 拉 backbone（首次换卡用）")
    ap.add_argument("--stop", action="store_true")
    args = ap.parse_args()

    creds = None
    password = None
    if args.ssh:
        creds = parse_ssh_line(args.ssh)
        password = args.password or None
        if not password:
            import getpass

            password = getpass.getpass(
                f"{creds['user']}@{creds['host']}:{creds['port']} 的密码（不回显）> ").strip()
    elif args.password:
        saved = _read_saved_creds()
        if saved is None:
            raise SystemExit("--password 需要配合 --ssh 使用（或先保存一份凭据）")
        creds = saved[0]
        password = args.password

    client, user, host, port = connect(creds=creds, password=password,
                                       ask=args.ask, save=(args.save or args.ask))
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

    # ---------------- 体检 ----------------
    model_abs = cloud_paths.remote_model(args.model_dir or DEFAULT_MODEL_REL)
    dmem_abs = f"{REMOTE_ROOT}/models/dmem-261018/dmem.safetensors"

    def preflight() -> list[dict]:
        py = cloud_paths.remote_python()
        checks = []

        def add(name, ok, detail=""):
            checks.append({"name": name, "ok": bool(ok), "detail": detail})

        out = run("uname -sr; nproc", timeout=20)
        add("远端 shell", bool(out) and "<<" not in out, out.replace("\n", " ")[:80])

        out = run(f"{py} -V 2>&1", timeout=20)
        add("python", "Python 3" in out, out.strip()[:60])

        out = run(f"{py} -c \"import torch;print(torch.__version__, torch.cuda.is_available())\" 2>&1", timeout=90)
        add("torch + cuda", "True" in out, out.strip()[:70])

        out = run(f"{py} -c \"import transformers;print(transformers.__version__)\" 2>&1", timeout=60)
        add("transformers", out.strip()[:20] and "Error" not in out, out.strip()[:40])

        out = run(f"test -f {model_abs}/config.json && echo yes || echo no", timeout=20)
        add("backbone", out.strip().endswith("yes"), model_abs)

        out = run(f"test -f {dmem_abs} && echo yes || echo no", timeout=20)
        add("δ-mem 权重", out.strip().endswith("yes"), dmem_abs)

        out = run(f"test -d {REMOTE_ROOT}/meowllm && echo yes || echo no", timeout=20)
        add("代码目录", out.strip().endswith("yes"), f"{REMOTE_ROOT}/meowllm")

        out = run("nvidia-smi --query-gpu=name,memory.total,memory.used "
                  "--format=csv,noheader 2>&1", timeout=25)
        add("GPU", "MiB" in out, out.strip()[:70])
        return checks

    def print_preflight(checks: list[dict]) -> None:
        print("\n--- 云端体检 ---")
        for c in checks:
            mark = "✓" if c["ok"] else "✗"
            print(f"  {mark} {c['name']:<12} {c['detail']}")
        bad = [c["name"] for c in checks if not c["ok"]]
        print("  " + ("全部通过" if not bad else "需要处理：" + "、".join(bad)) + "\n")

    def setup_remote() -> None:
        """装依赖 + 拉 backbone（首次换卡时用）。"""
        py = cloud_paths.remote_python()
        repo = args.model_dir or DEFAULT_MODEL_REL
        repo = repo[len("models/"):] if repo.startswith("models/") else repo
        hf_repo = repo if "/" in repo else f"Qwen/{repo}"
        print(f"[setup] 远端装依赖（fastapi/uvicorn/pyyaml/openai/transformers/safetensors）…")
        print(run(f"{py} -m pip install -q --upgrade pip 2>&1 | tail -1", timeout=300))
        print(run(f"{py} -m pip install -q fastapi uvicorn pyyaml openai "
                  f"transformers safetensors huggingface_hub 2>&1 | tail -3", timeout=1800))
        print(f"[setup] 确认 backbone：{model_abs}（HF: {hf_repo}）")
        script = (
            f"mkdir -p {model_abs} && "
            f"{py} - <<'PY'\n"
            f"import os\n"
            f"from huggingface_hub import snapshot_download\n"
            f"local = {model_abs!r}\n"
            f"if not os.path.isfile(os.path.join(local, 'config.json')):\n"
            f"    print('downloading', {hf_repo!r}, '->', local, flush=True)\n"
            f"    snapshot_download(repo_id={hf_repo!r}, local_dir=local,\n"
            f"                      allow_patterns=['*.json','*.safetensors','*.txt'])\n"
            f"print('model ok', os.path.getsize(os.path.join(local,'model.safetensors'))//2**20, 'MB')\n"
            f"PY"
        )
        print(run(script, timeout=3600))

    if args.preflight or args.setup:
        checks = preflight()
        print_preflight(checks)
        if args.setup:
            setup_remote()
            print_preflight(preflight())
        client.close()
        return 0 if all(c["ok"] for c in checks) or args.setup else 1

    # 新卡最常见的两件事：云端没有代码 / 没有模型。代码能自动补，模型要 --setup。
    code_ok = run(f"test -d {REMOTE_ROOT}/meowllm && test -f {REMOTE_ROOT}/config.yml "
                  "&& echo yes || echo no", timeout=20).strip().endswith("yes")
    if not code_ok:
        print("[cloud] 云端还没有代码（新实例），先上传一次（cloud.py upsync）…")
        import subprocess

        rc = subprocess.run([sys.executable, str(_TRAIN_DIR / "cloud.py"), "upsync"]).returncode
        if rc != 0:
            print("[cloud] 上传失败；可手动跑：python labs\\dmem_train\\cloud.py upsync")
        else:
            print("[cloud] 代码已上传")

    # 起服务前先体检：换卡后最常见的就是"模型不在"和"依赖没装"
    checks = preflight()
    if not all(c["ok"] for c in checks):
        print_preflight(checks)
        print("[cloud] 体检没全过。加 --setup 让我在云端装依赖并拉模型，"
              "或先在云端手动准备好；只想看体检结果用 --preflight。")
        if not remote_healthy():
            client.close()
            return 1
        print("[cloud] 但云端 18100 还活着，继续挂隧道")


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
