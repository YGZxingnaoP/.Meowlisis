# -*- coding: utf-8 -*-
"""把「本地面板」接到「云端训练」：读状态 / 启停训练，全走 SSH（密码直连）。

为什么需要它
------------
本地面板原本只能起**本机**训练进程（`subprocess.Popen`），但 8B 只有云上有卡。
这里用 paramiko 把同一套动作搬到远端，面板的 HTML/JS 一行都不用改 —— 它读的
仍然是 `status.json` / `metrics.jsonl` / `train.log`，只是这三个文件变成 SFTP 拉的。
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:                     # 既支持 python remote.py，也支持被 import
    sys.path.insert(0, HERE)
import cloud_paths  # noqa: E402  —— 远端路径的唯一出处

MODULE_ROOT = cloud_paths.MODULE_ROOT
CRED_DIR = os.path.join(MODULE_ROOT, "labs", "autoDL")
REMOTE_DIR = cloud_paths.remote(cloud_paths.REL_TRAIN)
REMOTE_PY = f"export PATH={cloud_paths.remote_bin_dir()}:$PATH;"

#: 云端启动器：一次上传，之后只传参数。
#: 为什么不用 Python 拼 shell 命令：PATH / $ / 引号在 SSH 里反复出问题，
#: 而"固定脚本 + 三个参数"几乎没有出错的余地。脚本自己做三件事：
#:   1) 固定 PATH   2) setsid 脱离   3) 写 pidfile 并等 8 秒确认活着
#: DIR / PATH 由 `launch_sh()` 在运行时从 cloud_paths 填进来，
#: 所以改远端根只需要改一处（环境变量 MEOWLLM_REMOTE_ROOT 即可）。
LAUNCH_SH_TEMPLATE = r"""#!/bin/bash
set -u
export PATH=@BIN@:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/root/miniconda3/bin
DIR=@DIR@
cd "$DIR" 2>/dev/null || { echo "CD_FAIL"; exit 9; }

OUT="${1:-}"; shift || true
DATA="${1:-data/sft.jsonl}"; shift || true
[ -z "$OUT" ] && { echo "NO_OUT"; exit 2; }
mkdir -p "$OUT" || { echo "MKDIR_FAIL"; exit 2; }
PIDF="$OUT/train.pid"

if [ -f "$PIDF" ]; then
  OLD="$(cat "$PIDF" 2>/dev/null || true)"
  if [ -n "${OLD:-}" ] && kill -0 "$OLD" 2>/dev/null; then
    echo "ALREADY_RUNNING $OLD"; exit 3
  fi
fi
[ -f "$DATA" ] || { echo "NO_DATA $DATA"; exit 4; }

setsid nohup python3 -u train_sft.py --data "$DATA" --out "$OUT" "$@" \
  > "$OUT/train.log" 2>&1 < /dev/null &
PID=$!
echo "$PID" > "$PIDF"

sleep 8
if kill -0 "$PID" 2>/dev/null; then
  echo "STARTED $PID"
else
  echo "DIED_EARLY"
  echo "----- train.log -----"
  tail -30 "$OUT/train.log" 2>/dev/null || echo "(no log)"
fi
"""


def launch_sh() -> str:
    """云端启动器（把远端根/bin 代进去，保持单一出处）。"""
    return (LAUNCH_SH_TEMPLATE
            .replace("@DIR@", REMOTE_DIR)
            .replace("@BIN@", cloud_paths.remote_bin_dir()))


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def credentials() -> dict:
    login = os.path.join(CRED_DIR, "登录指令.txt")
    passwd = os.path.join(CRED_DIR, "密码.txt")
    if not os.path.isfile(login) or not os.path.isfile(passwd):
        raise RuntimeError(f"缺少凭据：{login} / {passwd}")
    text = _decode(open(login, "rb").read()).strip()
    cred = {"user": "root", "host": "", "port": 22,
            "password": _decode(open(passwd, "rb").read()).strip()}
    parts = text.split()
    for i, token in enumerate(parts):
        if token == "-p" and i + 1 < len(parts) and parts[i + 1].isdigit():
            cred["port"] = int(parts[i + 1])          # ssh -p 49229 root@...
        elif token.startswith("-p") and token[2:].isdigit():
            cred["port"] = int(token[2:])             # ssh -p49229 root@...
        elif "@" in token and not token.startswith("-"):
            cred["user"], cred["host"] = token.split("@", 1)
    if not cred["host"] and parts:
        cred["host"] = parts[-1].split("@")[-1]
    if not cred["host"]:
        raise RuntimeError(f"登录指令解析失败：{text!r}")
    return cred


class Remote:
    """一个长连接 + 若干薄包装。断了自动重连一次。"""

    def __init__(self) -> None:
        self.cred = credentials()
        self._client = None
        self._sftp = None
        # paramiko 的 client/sftp **不是线程安全的**。面板每次刷新会并发打
        # /api/runs、/api/state、/chart.svg 三个请求，共用一条连接会互相撞死
        # （现象：页面永远停在"连接中…"，刷新后整个面板无响应）。
        # 用一把进程级 RLock 把所有远端操作串起来。
        self._lock = threading.RLock()

    # ------------------------------------------------------------ 连接
    def _connect(self) -> None:
        import paramiko

        if self._client is not None:
            return
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=self.cred["host"], port=self.cred["port"],
                       username=self.cred["user"],
                       password=self.cred["password"], timeout=20,
                       banner_timeout=20, auth_timeout=20)
        self._client = client
        self._sftp = client.open_sftp()

    def close(self) -> None:
        for item in (self._sftp, self._client):
            try:
                if item:
                    item.close()
            except Exception:  # noqa: BLE001
                pass
        self._sftp = self._client = None

    def run(self, command: str, timeout: int = 300) -> tuple[int, str]:
        with self._lock:
            for attempt in (1, 2):
                try:
                    self._connect()
                    _in, out, err = self._client.exec_command(command,
                                                              timeout=timeout)
                    body = out.read().decode("utf-8", "replace")
                    body += err.read().decode("utf-8", "replace")
                    return out.channel.recv_exit_status(), body.strip()
                except Exception:  # noqa: BLE001
                    self.close()
                    if attempt == 2:
                        raise
            return 1, ""

    # ------------------------------------------------------------ 读文件
    def read_text(self, remote: str) -> str:
        with self._lock:
            try:
                self._connect()
                with self._sftp.open(remote, "r") as fh:
                    return fh.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                return ""

    def read_json(self, remote: str) -> dict:
        text = self.read_text(remote)
        try:
            return json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            return {}

    def read_jsonl(self, remote: str, limit: int = 5000) -> list[dict]:
        rows = []
        for line in self.read_text(remote).splitlines()[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def put_text(self, remote: str, text: str) -> None:
        self._connect()
        folder = posixpath.dirname(remote)
        self.run(f"mkdir -p {folder}")
        with self._sftp.open(remote, "w") as fh:
            fh.write(text)

    # ------------------------------------------------------------ 动作
    def runs(self) -> list[dict]:
        """列出云端所有运行记录（out/*/），按更新时间倒序。

        实现故意**不用远端 python 脚本**（之前那段内联脚本在远端静默失败，
        /api/runs 直接返回空）。这里只 ls 一次目录，再逐个 SFTP 读两个小 json，
        20 条记录也只要 1~2 秒，且没有引号/格式化/版本的坑。
        """
        code, body = self.run(f"ls -1d {REMOTE_DIR}/out/*/ 2>/dev/null || true")
        dirs = [d.strip().rstrip("/") for d in body.splitlines() if d.strip()]
        rows: list[dict] = []
        for path in dirs:
            name = posixpath.basename(path)
            status = self.read_json(posixpath.join(path, "status.json"))
            if not status:
                continue
            ev = self.read_json(posixpath.join(path, "eval.json"))
            try:
                mtime = self._sftp.stat(posixpath.join(path, "status.json")).st_mtime
            except Exception:  # noqa: BLE001
                mtime = 0
            gap = ev.get("gap")
            rows.append({"out": f"out/{name}", "step": status.get("step"),
                         "total": status.get("total"),
                         "progress": status.get("progress"),
                         "loss": status.get("loss"), "eta_s": status.get("eta_s"),
                         "elapsed_s": status.get("elapsed_s"),
                         "state": status.get("state"), "phase": status.get("phase"),
                         "updated_at": status.get("updated_at"),
                         "mtime": mtime, "gap": gap,
                         "no_context": ev.get("no_context"),
                         "with_state": ev.get("with_state")})
        rows.sort(key=lambda r: -(r.get("mtime") or 0))

        # status.json 只反映"写它时"的状态；进程被杀后文件里仍是 running。
        # 用真实进程数校正，否则表里会出现好几条"运行中"（实测踩过）。
        alive = False
        try:
            _c, procs = self.run("pgrep -c -f '[t]rain_sft.py' || true")
            last = (procs.strip().splitlines() or ["0"])[-1].strip()
            alive = last.isdigit() and int(last) > 0
        except Exception:  # noqa: BLE001
            alive = False
        if not alive:
            for row in rows:
                if row.get("state") == "running":
                    row["state"] = "interrupted"
        else:
            running_rows = [r for r in rows if r.get("state") == "running"]
            running_rows.sort(key=lambda r: -(r.get("mtime") or 0))
            for row in running_rows[1:]:
                row["state"] = "interrupted"
        return rows

    def state(self, out_dir: str, log_tail: int = 80) -> dict:
        # out_dir 可能是面板传下来的本地绝对路径 —— 必须先规整成相对路径，
        # 否则远端会变成 /root/.../D:\.Meowlisis\...\out（历史 bug）。
        out_dir = cloud_paths.out_rel(out_dir)
        base = posixpath.join(REMOTE_DIR, out_dir)
        status = self.read_json(posixpath.join(base, "status.json"))
        metrics = self.read_jsonl(posixpath.join(base, "metrics.jsonl"))
        eval_body = self.read_json(posixpath.join(base, "eval.json"))
        log = self.read_text(posixpath.join(base, "train.log")).splitlines()[-log_tail:]
        _, procs = self.run("pgrep -fa '[t]rain_sft.py' | head -3 || true")
        running = "train_sft.py" in procs
        pid = None
        for line in procs.splitlines():
            parts = line.split()
            if parts and parts[0].isdigit():
                pid = int(parts[0])
                break
        if not running and status.get("state") == "running" and metrics:
            status["state"] = "stopped"
        return {"running": running, "pid": pid, "out_dir": out_dir,
                "argv": status.get("argv") or [], "status": status,
                "metrics": metrics, "eval": eval_body, "log": log,
                "server_time": time.strftime("%H:%M:%S"), "remote": True}

    def start(self, argv: list[str], out_dir: str,
              data: str = "data/sft.jsonl") -> dict:
        """启动云端训练。argv 只放**额外参数**（--rank/--chunk/--model…），
        --data / --out 由 launch.sh 负责。"""
        import shlex

        out_dir = cloud_paths.out_rel(out_dir)
        launcher = posixpath.join(REMOTE_DIR, "launch.sh")
        self.put_text(launcher, launch_sh())
        self.run(f"chmod +x {launcher}")
        parts = [f"bash {launcher}", shlex.quote(out_dir), shlex.quote(data)]
        parts += [shlex.quote(str(a)) for a in argv]
        code, body = self.run(" ".join(parts), timeout=150)
        pid, state = None, "unknown"
        for token in re.findall(r"(STARTED|ALREADY_RUNNING)\s+(\d+)", body):
            state, pid = token[0], int(token[1])
        if state == "STARTED":
            return {"ok": True, "pid": pid, "argv": argv, "out": out_dir,
                    "body": body}
        if state == "ALREADY_RUNNING":
            return {"ok": False, "pid": pid, "out": out_dir, "body": body,
                    "error": f"云端已经在跑了（pid {pid}）"}
        return {"ok": False, "pid": None, "argv": argv, "out": out_dir,
                "body": body,
                "error": (body.split("----- train.log -----")[-1].strip()
                          or body.strip() or "启动失败（无输出）")}

    def stop(self) -> dict:
        code, body = self.run("pkill -f 'train_sft.py'; sleep 1; "
                              "pgrep -c -f 'train_sft.py' || true")
        return {"ok": True, "state": "stopped", "body": body}

    def files(self) -> list[dict]:
        base = posixpath.join(REMOTE_DIR, "data")
        code, body = self.run(f"ls -l --time-style=+%m-%d_%H:%M {base}/*.jsonl 2>/dev/null")
        items = []
        for line in body.splitlines():
            parts = line.split()
            if len(parts) < 7:
                continue
            name = parts[-1].split("/")[-1]
            items.append({"name": name, "path": f"{base}/{name}",
                          "dir": "remote:data", "size": int(parts[4]),
                          "mtime": parts[5]})
        items.sort(key=lambda x: -x["size"])
        return items

    def dataset(self, data_path: str) -> dict:
        """远端算一个粗略画像（字符长度，不加载 tokenizer）。"""
        remote = data_path if data_path.startswith("/") else \
            posixpath.join(REMOTE_DIR, "data", data_path)
        script = (
            "import json,sys;from collections import Counter\n"
            "ctx=[];ans=[];src=Counter();n=0\n"
            f"for line in open({remote!r},encoding='utf-8'):\n"
            "    line=line.strip()\n"
            "    if not line: continue\n"
            "    r=json.loads(line);n+=1\n"
            "    src[str(r.get('source') or '?')]+=1\n"
            "    ctx.append(len(str(r.get('context') or '')))\n"
            "    ans.append(len(str(r.get('response') or '')))\n"
            "print(json.dumps({'rows':n,'sources':dict(src.most_common(8)),"
            "'ctx_mean':int(sum(ctx)/max(1,len(ctx))),'ctx_max':max(ctx or [0]),"
            "'ans_mean':int(sum(ans)/max(1,len(ans)))}))\n"
        )
        self.put_text(posixpath.join(REMOTE_DIR, ".profile.py"), script)
        code, body = self.run(f"cd {REMOTE_DIR} && {REMOTE_PY} python3 .profile.py")
        try:
            row = json.loads(body.splitlines()[-1])
        except Exception:  # noqa: BLE001
            return {"exists": False, "path": remote, "raw": body[:400]}
        return {"exists": bool(row.get("rows")), "path": remote,
                "rows": row.get("rows", 0), "sources": row.get("sources", {}),
                "context_chars": {"mean": row.get("ctx_mean", 0),
                                  "max": row.get("ctx_max", 0),
                                  "counts": [], "min": 0},
                "answer_chars": {"mean": row.get("ans_mean", 0), "counts": [],
                                 "min": 0, "max": row.get("ans_mean", 0)}}


def main() -> int:
    """自测：python remote.py [status|files|dataset]"""
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    rm = Remote()
    try:
        if action == "status":
            st = rm.state("out")
            print(json.dumps({k: st[k] for k in ("running", "pid", "remote")},
                             ensure_ascii=False))
            print("status:", json.dumps(st["status"], ensure_ascii=False)[:300])
            print("metrics:", len(st["metrics"]), "点")
        elif action == "files":
            for item in rm.files():
                print(f"  {item['name']:24s} {item['size']/1024:8.0f}KB  {item['mtime']}")
        elif action == "dataset":
            print(json.dumps(rm.dataset("sft.jsonl"), ensure_ascii=False)[:500])
        return 0
    finally:
        rm.close()


#: 训练用的 backbone：相对模块根（云端/本地同一套相对路径）。
#: 想换成本地 0.6B 跑通管道：--model models/Qwen3-0.6B，或直接改这里。
DEFAULT_MODEL = cloud_paths.DEFAULT_TRAIN_MODEL_REL
DEFAULT_LAUNCH_ARGS = ["--model", DEFAULT_MODEL, "--rank", "64", "--chunk", "16",
                       "--context-len", "768", "--accum", "2", "--epochs", "1",
                       "--save-every", "50"]


def run_start_stop(action: str, out_dir: str = cloud_paths.DEFAULT_RUN) -> int:
    """给 .bat 用的极简启停：不经过面板/HTTP/JSON，结果直接打在控制台。

    失败时把云端 launch.sh 的原样输出（含日志尾部）打出来，并返回非 0，
    这样批处理的 `if errorlevel` 能判断，窗口也会 pause 住让人看清。
    """
    out_dir = cloud_paths.out_rel(out_dir)
    rm = Remote()
    try:
        if action == "stop":
            code, body = rm.run(
                f"PIDF={REMOTE_DIR}/{out_dir}/train.pid; "
                f"if [ -f $PIDF ]; then P=$(cat $PIDF); kill -TERM $P 2>/dev/null; "
                f"sleep 2; kill -9 $P 2>/dev/null; echo STOPPED $P; "
                f"else echo NO_PIDFILE; fi")
            print(body)
            return 0
        print(f"目标输出目录: {out_dir}")
        print(f"模型: {DEFAULT_MODEL}（相对模块根；云端在 {REMOTE_DIR}/../.. 下）")
        print("正在启动（会等 8 秒确认进程活着）...\n")
        result = rm.start(DEFAULT_LAUNCH_ARGS, out_dir, data="data/sft.jsonl")
        if result.get("ok"):
            print("=" * 60)
            print(f"  启动成功   pid = {result['pid']}")
            print(f"  输出目录   {out_dir}")
            print("=" * 60)
            print("现在可以用面板看进度（只读，不影响训练），"
                  "或 start_dashboard_remote.bat。")
            return 0
        print("=" * 60)
        print("  启动失败")
        print("=" * 60)
        print(result.get("error") or result.get("body") or "(无输出)")
        return 1
    except Exception as exc:  # noqa: BLE001
        print("=" * 60)
        print("  连接/启动异常")
        print("=" * 60)
        print(f"{type(exc).__name__}: {exc}")
        return 2
    finally:
        rm.close()


BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values, width: int = 56) -> str:
    """把一串 loss 压成一行 ASCII/Unicode 折线。终端里画，永远不可能白屏。"""
    vals = [float(v) for v in values if v is not None and v == v]
    if not vals:
        return ""
    if len(vals) > width:
        step = len(vals) / width
        pts = [vals[min(len(vals) - 1, int(i * step))] for i in range(width)]
    else:
        pts = vals
    lo, hi = min(pts), max(pts)
    if hi - lo < 1e-9:
        hi = lo + 1.0
    return "".join(BLOCKS[min(7, max(0, int((v - lo) / (hi - lo) * 7)))]
                   for v in pts)


def watch(out_dir: str = "out/r64-ctx768-a2", interval: int = 10) -> int:
    """一个窗口盯到底：每 interval 秒打印进度（复用同一条 SSH 连接）。"""
    import time as _t

    rm = Remote()
    started = _t.time()
    try:
        while True:
            try:
                st = rm.state(out_dir, log_tail=3)
            except Exception as exc:  # noqa: BLE001
                print(f"[{_t.strftime('%H:%M:%S')}] 连接失败：{exc}", flush=True)
                rm.close()
                _t.sleep(interval)
                continue
            s = st.get("status") or {}
            if not s:
                print(f"\n[{_t.strftime('%H:%M:%S')}] "
                      f"{'RUNNING' if st.get('running') else 'WAITING'}  out={out_dir}")
                print("  还没有 status.json —— 模型加载中（8B 约 60~90 秒）")
                _t.sleep(interval)
                continue
            pct = float(s.get("progress") or 0)
            filled = int(pct * 28)
            bar = "#" * filled + "-" * (28 - filled)
            eta = s.get("eta_s")
            eta_txt = f"{int(eta) // 60}m{int(eta) % 60:02d}s" if eta else "--"
            print(f"\n[{_t.strftime('%H:%M:%S')}] "
                  f"{'RUNNING' if st.get('running') else 'STOPPED'}  "
                  f"pid={st.get('pid')}  out={out_dir}")
            print(f"  [{bar}] {pct * 100:5.1f}%   step {s.get('step')}/{s.get('total')}")
            print(f"  loss={s.get('loss')}  lr={s.get('lr')}  "
                  f"elapsed={s.get('elapsed_s')}s  eta={eta_txt}")
            ev = st.get("eval") or {}
            if ev.get("gap") is not None:
                print(f"  评测: no-context {ev.get('no_context')} vs "
                      f"with-state {ev.get('with_state')}  gap={ev.get('gap')}")
            # ★ 终端折线图（loss）
            losses = [p.get("loss") for p in (st.get("metrics") or [])]
            line = sparkline(losses)
            if line:
                good = [v for v in losses if v is not None]
                print(f"  loss  {line}")
                print(f"        最早 {good[0]:.3f} → 现在 {good[-1]:.3f} "
                      f"(最低 {min(good):.3f} / 最高 {max(good):.3f}, {len(good)} 点)")
            for log_line in (st.get("log") or [])[-2:]:
                print(f"  | {log_line}")
            if s.get("state") in ("finished", "error") and not st.get("running"):
                print(f"\n训练结束（state={s.get('state')}），总耗时 "
                      f"{int(_t.time() - started)}s。")
                return 0
            _t.sleep(interval)
    except KeyboardInterrupt:
        print("\n已退出监控（训练不受影响，仍在云端跑）。")
        return 0
    finally:
        rm.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("start", "stop"):
        _out = sys.argv[2] if len(sys.argv) > 2 else "out/r64-ctx768-a2"
        raise SystemExit(run_start_stop(sys.argv[1], _out))
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        _out = sys.argv[2] if len(sys.argv) > 2 else "out/hangdiag"
        _iv = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        raise SystemExit(watch(_out, _iv))
    raise SystemExit(main())
