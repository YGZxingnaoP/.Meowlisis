# -*- coding: utf-8 -*-
"""AutoDL 云机操作：检查 / 上传 / 装环境 / 取数据 / 起面板（密码直连）。

凭据从本模块的 `labs/autoDL/` 读（已被 .gitignore 排除，不会入库）：
    labs/autoDL/登录指令.txt    ssh -p 49229 root@connect.westb.seetacloud.com
    labs/autoDL/密码.txt        <password>

用法
----
    python cloud.py check                    # 连上看看卡/盘/Python
    python cloud.py upsync                   # 上传训练包（跳过已存在的同尺寸文件）
    python cloud.py setup                    # pip 依赖 + 找/下模型
    python cloud.py fetch-data               # 用学术加速拉 LoCoMo / PerLTQA
    python cloud.py serve                    # 后台起面板，打印隧道命令
    python cloud.py all                      # check + upsync + setup + serve
    python cloud.py run -- "nvidia-smi"      # 在远端执行任意命令

只依赖 paramiko（本机 runtime 已带）。
"""

from __future__ import annotations

import argparse
import os
import posixpath
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:                     # 既支持 python cloud.py，也支持被 import
    sys.path.insert(0, HERE)
import cloud_paths  # noqa: E402  —— 远端路径的唯一出处，别在本文件另写死

MODULE_ROOT = cloud_paths.MODULE_ROOT
PROJECT_ROOT = cloud_paths.PROJECT_ROOT
CRED_DIR = os.path.join(MODULE_ROOT, "labs", "autoDL")
REMOTE_ROOT = cloud_paths.remote_root()

#: 上传白名单：(本地相对路径, 远端相对路径)
#: 云端结构与本地**一一对应**：模块根下同名相对路径，所以 config.yml 不用改。
UPLOAD = [
    # 整个推理包都传：引擎/服务端的改动必须和本地一致，否则云端跑的是旧逻辑
    ("meowllm", "meowllm"),
    ("labs/dmem_train", "labs/dmem_train"),      # 含 data/ 与 presets/；不含 out/
    ("docs/notes", "docs/notes"),
    ("api.md", "api.md"),                        # 协议说明：云端保留同一份
    ("config.yml", "config.yml"),
]
#: 项目根下的额外目录
UPLOAD_PROJECT = [
    ("character/abstract_memory", "character/abstract_memory"),
]
#: models/ 刻意**不**上传：1.5GB+，由 cloud.py setup 在云端按同结构下载
SKIP_DIRS = {"__pycache__", ".git", "out", ".vs", ".dmem_work"}
SKIP_EXT = {".zip", ".pyc", ".log", ".pt", ".safetensors", ".gguf", ".bin"}


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def read_credentials() -> dict:
    login = os.path.join(CRED_DIR, "登录指令.txt")
    passwd = os.path.join(CRED_DIR, "密码.txt")
    if not os.path.isfile(login):
        raise SystemExit(f"缺少凭据文件：{login}")
    text = _decode(open(login, "rb").read()).strip()
    parts = text.split()
    cred = {"user": "root", "host": "", "port": 22, "password": ""}
    for i, token in enumerate(parts):
        if token == "-p" and i + 1 < len(parts):
            cred["port"] = int(parts[i + 1])
        elif "@" in token:
            cred["user"], cred["host"] = token.split("@", 1)
    if not cred["host"] and len(parts) >= 2:
        cred["host"] = parts[-1]
    if os.path.isfile(passwd):
        cred["password"] = _decode(open(passwd, "rb").read()).strip()
    if not cred["host"] or not cred["password"]:
        raise SystemExit("登录指令/密码 解析失败，检查 labs/autoDL/ 下两个文件")
    return cred


class Cloud:
    def __init__(self, quiet: bool = False) -> None:
        import paramiko

        self.cred = read_credentials()
        self.quiet = quiet
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if not quiet:
            print(f"连接 {self.cred['user']}@{self.cred['host']}:{self.cred['port']} ...")
        self.client.connect(hostname=self.cred["host"], port=self.cred["port"],
                            username=self.cred["user"],
                            password=self.cred["password"], timeout=25,
                            banner_timeout=25, auth_timeout=25)
        self.sftp = self.client.open_sftp()
        if not quiet:
            print("已连接。")

    def close(self) -> None:
        try:
            self.sftp.close()
            self.client.close()
        except Exception:  # noqa: BLE001
            pass

    def run(self, command: str, timeout: int = 120, show: bool = True) -> tuple[int, str]:
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout,
                                                         get_pty=False)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        body = (out + err).strip()
        if show and body:
            print(body)
        return code, body

    def makedirs(self, remote: str) -> None:
        parts = remote.strip("/").split("/")
        path = ""
        for part in parts:
            path += "/" + part
            try:
                self.sftp.stat(path)
            except IOError:
                try:
                    self.sftp.mkdir(path)
                except IOError:
                    pass

    def put_dir(self, local: str, remote: str) -> tuple[int, int]:
        """递归上传，跳过同尺寸文件。返回 (上传数, 跳过数)。"""
        sent = skipped = 0
        self.makedirs(remote)
        for root, dirs, files in os.walk(local):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            rel = os.path.relpath(root, local)
            target = remote if rel == "." else posixpath.join(remote,
                                                             rel.replace("\\", "/"))
            self.makedirs(target)
            for name in files:
                ext = os.path.splitext(name)[1].lower()
                if ext in SKIP_EXT:
                    continue
                src = os.path.join(root, name)
                dst = posixpath.join(target, name)
                size = os.path.getsize(src)
                try:
                    if self.sftp.stat(dst).st_size == size:
                        skipped += 1
                        continue
                except IOError:
                    pass
                self.sftp.put(src, dst)
                sent += 1
        return sent, skipped

    def put_file(self, local: str, remote: str) -> None:
        self.makedirs(posixpath.dirname(remote))
        self.sftp.put(local, remote)


# ------------------------------------------------------------------ 子命令
def cmd_sync_model(cl: Cloud, args) -> int:
    """把本地模型目录直接传上去（跳过已存在且同尺寸的文件）。

    为什么需要：云上 `pip`/`huggingface_hub` 拉 1.4GB 经常只有几百 KB/s，
    而本地上行往往更快；而且这个模型本地已经有了，没必要再下一遍。
    """
    local = args.local or cloud_paths.local(cloud_paths.LOCAL_MODEL_REL)
    remote = args.remote or cloud_paths.remote(cloud_paths.LOCAL_MODEL_REL)
    if not os.path.isdir(local):
        print(f"本地模型不存在：{local}")
        return 1
    files = [f for f in sorted(os.listdir(local))
             if os.path.isfile(os.path.join(local, f))]
    total = sum(os.path.getsize(os.path.join(local, f)) for f in files)
    print(f"本地 {local}")
    print(f"  {len(files)} 个文件，共 {total / 2**20:.0f} MB -> {remote}")
    cl.makedirs(remote)
    sent = skipped = 0
    began = time.time()
    for name in files:
        src = os.path.join(local, name)
        dst = posixpath.join(remote, name)
        size = os.path.getsize(src)
        try:
            if cl.sftp.stat(dst).st_size == size:
                print(f"  跳过（已同步）{name}")
                skipped += 1
                continue
        except IOError:
            pass
        t0 = time.time()
        cl.sftp.put(src, dst, callback=_progress(name, size, began))
        print(f"  {name} {size / 2**20:.0f}MB 用时 {time.time() - t0:.1f}s")
        sent += 1
    print(f"完成：上传 {sent}，跳过 {skipped}，总计 {time.time() - began:.0f}s")
    code, body = cl.run(f"ls -la {remote} | tail -8")
    return 0


_LAST = {"t": 0.0}


def _progress(name: str, size: int, began: float):
    def cb(done: int, _total: int) -> None:
        now = time.time()
        if now - _LAST["t"] < 2.0 and done < size:
            return
        _LAST["t"] = now
        pct = done / max(1, size) * 100
        elapsed = max(1e-6, now - began)
        print(f"    {name}: {pct:5.1f}%  {done / 2**20:.0f}/{size / 2**20:.0f}MB")

    return cb


def cmd_check(cl: Cloud, _args) -> int:
    print("=" * 60)
    cl.run("hostname; uname -a | cut -c1-90")
    cl.run("nvidia-smi --query-gpu=name,memory.total,memory.used "
           "--format=csv,noheader")
    cl.run("nproc; free -g | head -2")
    cl.run("df -h /root /root/autodl-tmp 2>/dev/null | sed 's/  */ /g'")
    cl.run("python -V; which python python3")
    cl.run("python -c \"import torch;print('torch',torch.__version__,"
           "'cuda',torch.version.cuda,torch.cuda.is_available())\" 2>&1 | tail -2")
    cl.run("python -c \"import transformers;print('transformers',"
           "transformers.__version__)\" 2>&1 | tail -1")
    print("--- 已有模型/数据 ---")
    cl.run("ls -d /root/autodl-tmp/*/ 2>/dev/null | head -20")
    cl.run(f"ls {cloud_paths.remote(cloud_paths.REL_MODELS)} 2>/dev/null | head -10")
    cl.run(f"ls {REMOTE_ROOT}/labs/dmem_train/data 2>/dev/null | head -10")
    cl.run("for p in /autodl-pub /autodl-pub/data; do [ -d $p ] && echo \"$p:\" && "
           "ls $p 2>/dev/null | head -5; done")
    cl.run("find /root/autodl-tmp -maxdepth 4 -name 'config.json' -path '*Qwen3*' "
           "2>/dev/null | head -5")
    return 0


def cmd_upsync(cl: Cloud, _args) -> int:
    total_sent = total_skip = 0
    for rel, remote_rel in UPLOAD + UPLOAD_PROJECT:
        base = MODULE_ROOT if (rel, remote_rel) in UPLOAD else PROJECT_ROOT
        local = os.path.join(base, rel)
        target = posixpath.join(REMOTE_ROOT, remote_rel)
        if os.path.isfile(local):                    # 单文件（config.yml 这类）
            try:
                same = cl.sftp.stat(target).st_size == os.path.getsize(local)
            except IOError:
                same = False
            if same:
                print(f"  {rel:24s} 已同步")
                total_skip += 1
                continue
            cl.put_file(local, target)
            print(f"  {rel:24s} 上传 1 -> {target}")
            total_sent += 1
            continue
        if not os.path.isdir(local):
            print(f"跳过（本地不存在）：{rel}")
            continue
        sent, skipped = cl.put_dir(local, target)
        total_sent += sent
        total_skip += skipped
        print(f"  {rel:24s} 上传 {sent:4d} 跳过 {skipped:4d} -> {target}")
    print(f"合计：上传 {total_sent} 个，跳过 {total_skip} 个（同尺寸视为已同步）")
    return 0


SETUP = r"""
set -e
# AutoDL 的非交互 shell 里 python 不在 PATH（实测 python: command not found）
export PATH={bin}:/root/miniconda3/bin:$PATH
PY=$(command -v python3 || echo {py})
echo "PY=$PY"; $PY -V
cd {root}
export HF_ENDPOINT=${{HF_ENDPOINT:-https://hf-mirror.com}}
source /etc/network_turbo 2>/dev/null || true
$PY -m pip install -q --upgrade pip 2>/dev/null || true
$PY -m pip install -q "transformers==5.3.0" safetensors pyyaml openai fastapi uvicorn
$PY - <<'PY'
import torch, transformers
print("torch", torch.__version__, "cuda", torch.version.cuda,
      "avail", torch.cuda.is_available())
print("transformers", transformers.__version__)
PY
# 模型放在 <模块根>/models/ 下 —— 与本地完全同构，
# 于是 config.yml 里的相对路径 models/Qwen3-0.6B 在云端不用改一个字。
export MODEL={model}
mkdir -p "$MODEL"
if [ -f "$MODEL/config.json" ]; then
  echo "模型已存在：$MODEL"
else
  echo "拉取 Qwen3-0.6B -> $MODEL"
  $PY - <<'PY'
import os
from huggingface_hub import snapshot_download
local = os.environ["MODEL"]
snapshot_download(repo_id="Qwen/Qwen3-0.6B", local_dir=local,
                  allow_patterns=["*.json", "*.safetensors", "*.txt"])
print("ok", local, os.path.getsize(os.path.join(local, "model.safetensors")) // 2**20, "MB")
PY
fi
echo "SETUP_DONE"
"""


def cmd_setup(cl: Cloud, args) -> int:
    print("远端装依赖 + 准备模型（首次约 3~8 分钟）...")
    code, body = cl.run(f"mkdir -p {REMOTE_ROOT} && echo ok")
    script = SETUP.format(root=REMOTE_ROOT,
                          model=cloud_paths.remote(cloud_paths.LOCAL_MODEL_REL),
                          py=cloud_paths.remote_python(),
                          bin=cloud_paths.remote_bin_dir())
    # 长任务：写到远端脚本再执行，避免引号地狱
    remote_sh = posixpath.join(REMOTE_ROOT, ".setup.sh")
    with cl.sftp.open(remote_sh, "w") as fh:
        fh.write(script)
    cl.run(f"chmod +x {remote_sh}")
    begin = time.time()
    code, body = cl.run(f"bash {remote_sh} 2>&1 | tail -25", timeout=1800)
    print(f"（耗时 {time.time() - begin:.0f}s，退出码 {code}）")
    return 0 if "SETUP_DONE" in body else 1


def cmd_fetch_data(cl: Cloud, args) -> int:
    """拉真人数据集（AutoDL 学术加速）。

    落在 `<模块根>/labs/dmem_train/data/raw/` —— 与本地同一相对路径，
    所以 `build_from_real.py` 的默认相对路径在云端也成立。
    """
    script = r"""
set -e
cd {train}
export PATH={bin}:$PATH
mkdir -p data/raw
source /etc/network_turbo 2>/dev/null || true
export HF_ENDPOINT=${{HF_ENDPOINT:-https://hf-mirror.com}}
cd data/raw
if [ ! -d locomo ]; then
  git clone --depth 1 https://github.com/snap-research/locomo.git locomo || \
    echo "LoCoMo clone 失败（可改用 HF 镜像）"
else echo "locomo 已存在"; fi
if [ ! -d PerLTQA ]; then
  git clone --depth 1 https://github.com/Elvin-Yiming-Du/PerLTQA.git perltqa || \
    echo "PerLTQA clone 失败"
else echo "perltqa 已存在"; fi
echo "--- 产物 ---"
du -sh locomo perltqa 2>/dev/null || true
find locomo perltqa -name '*.json' 2>/dev/null | head -8
echo "FETCH_DONE"
""".format(train=cloud_paths.remote(cloud_paths.REL_TRAIN),
           bin=cloud_paths.remote_bin_dir())
    remote_sh = posixpath.join(REMOTE_ROOT, ".fetch.sh")
    with cl.sftp.open(remote_sh, "w") as fh:
        fh.write(script)
    cl.run(f"chmod +x {remote_sh}")
    code, body = cl.run(f"bash {remote_sh} 2>&1 | tail -30", timeout=900)
    return 0 if "FETCH_DONE" in body else 1


def cmd_serve(cl: Cloud, args) -> int:
    port = args.port
    train_dir = cloud_paths.remote(cloud_paths.REL_TRAIN)
    script = f"""
export PATH={cloud_paths.remote_bin_dir()}:/root/miniconda3/bin:$PATH
cd {train_dir}
mkdir -p out
pkill -f 'webui.py' 2>/dev/null || true
sleep 1
# setsid + nohup + </dev/null：SSH 通道一关就 SIGHUP，实测必须这么起
setsid nohup python3 -u webui.py --host 0.0.0.0 --port {port} --out out \
    > out/ui.log 2>&1 < /dev/null &
sleep 6
tail -6 out/ui.log
echo "--- probe ---"
for i in 1 2 3 4 5; do
  code=$(curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{port}/api/state 2>/dev/null || echo 000)
  echo "check $i: HTTP $code"
  [ "$code" = "200" ] && break
  sleep 2
done
echo "procs: $(ps -ef | grep -c '[w]ebui.py')"
"""
    print(f"远端后台起面板（端口 {port}）...")
    code, body = cl.run(script, timeout=180)
    host = cl.cred["host"]
    ssh_port = cl.cred["port"]
    print()
    print("=" * 64)
    print("  在你本机另开一个终端执行（密码用 labs\\autoDL\\密码.txt）：")
    print(f"    ssh -L {port}:127.0.0.1:{port} -p {ssh_port} "
          f"{cl.cred['user']}@{host}")
    print(f"  然后浏览器打开： http://127.0.0.1:{port}")
    print("=" * 64)
    return 0 if "HTTP 200" in body else 2


def cmd_run(cl: Cloud, args) -> int:
    command = args.command
    if isinstance(command, (list, tuple)):
        command = " ".join(command)
    command = str(command or "").strip()
    if not command:
        print("用法：python cloud.py run -- \"<远端命令>\"")
        return 2
    code, _ = cl.run(command, timeout=args.timeout)
    return code


def cmd_all(cl: Cloud, args) -> int:
    cmd_check(cl, args)
    print()
    cmd_upsync(cl, args)
    print()
    code = cmd_setup(cl, args)
    if code != 0:
        print("！！setup 没跑完，先解决问题再起面板")
        return code
    print()
    cmd_fetch_data(cl, args)
    print()
    cmd_serve(cl, args)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("check", "upsync", "setup", "sync-model",
                                    "fetch-data", "serve", "all", "run"))
    ap.add_argument("--port", type=int, default=6006, help="面板端口（远端+隧道）")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--local", default="", help="sync-model：本地模型目录")
    ap.add_argument("--remote", default="", help="sync-model：远端目标目录")
    ap.add_argument("command", nargs=argparse.REMAINDER,
                    help="cmd=run 时要执行的命令（后面全部内容）")
    args = ap.parse_args()

    cl = Cloud()
    try:
        func = {"check": cmd_check, "upsync": cmd_upsync, "setup": cmd_setup,
                "sync-model": cmd_sync_model, "fetch-data": cmd_fetch_data,
                "serve": cmd_serve, "all": cmd_all, "run": cmd_run}[args.cmd]
        return func(cl, args)
    finally:
        cl.close()


if __name__ == "__main__":
    raise SystemExit(main())
