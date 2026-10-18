# -*- coding: utf-8 -*-
"""δ-mem 训练前端（单文件，无 CDN 依赖，离线可用）。

功能
----
    * 一键启动 / 停止训练（子进程）
    * 实时看：loss 曲线、lr 曲线、进度条、ETA、已用时间
    * 看数据画像：样本数、来源分布、context/answer 长度分布
    * 训练结束后自动显示留出集结果（no-context vs with-state 的 NLL gap）
    * 日志尾部 80 行（stderr 也收）

为什么不用 TensorBoard / Streamlit
----------------------------------
AutoDL 上多一个依赖就多一个坑，而且要过 SSH 隧道转发端口。
这里只有 FastAPI + 原生 JS（图表用 canvas 手画），`pip install fastapi uvicorn` 就够。

用法
----
    # 本地
    ..\\..\\..\\..\\runtime\\311\\python.exe webui.py --port 8123

    # AutoDL（在实例里起，然后在你本机做端口转发）
    python webui.py --host 0.0.0.0 --port 6006
    # 本机：ssh -L 6006:127.0.0.1:6006 -p <端口> root@<实例地址>
    # 浏览器打开 http://127.0.0.1:6006
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_ROOT = os.path.dirname(os.path.dirname(HERE))   # .vendor/.MeowLLM
if HERE not in sys.path:                     # 既支持 python webui.py，也支持被 import
    sys.path.insert(0, HERE)
import cloud_paths  # noqa: E402  —— 远端路径的唯一出处

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse
except Exception as exc:  # noqa: BLE001
    print(f"需要 fastapi/uvicorn：pip install fastapi uvicorn（{exc}）")
    raise SystemExit(2)

STATE: dict = {"proc": None, "log_path": "", "argv": [], "started": 0.0}
DEFAULT_OUT = os.path.join(HERE, "out")
#: 远端模式：面板在本地，训练跑在 AutoDL（凭据读 labs/autoDL/）
REMOTE_MODE = False
#: 后端 backbone：**相对模块根**，云端/本地同一套相对路径（0.6B 用于本机验管道）
DEFAULT_MODEL = cloud_paths.DEFAULT_TRAIN_MODEL_REL
#: 推荐训练配置（8B / 24G 卡，实测可用；面板里直接就是这些值）
RECOMMENDED = {
    "rank": 64, "chunk": 16, "epochs": 1, "accum": 2, "lr": 2e-4,
    "context_len": 768, "layers": "", "max_steps": 0,
}
_RM = None
#: 远端快照缓存：三个并发请求共用一次 SSH 拉取，2 秒内不重复打。
_SNAP = {"ts": 0.0, "out": "", "data": None}
_SNAP_LOCK = threading.Lock()


def _snapshot(out: str, ttl: float = 2.0, force: bool = False) -> dict:
    """拿到远端状态快照（带 2 秒缓存，force=True 时无视缓存重新拉一次）。

    为什么必须缓存：浏览器每 2 秒请求 /api/state + /chart.svg，每个都做一次完整
    SSH 往返要 3~8 秒 → 请求排队 → 页面永远"连接中…"。

    为什么必须能 force：面板上的「刷新」按钮就是"我现在就要最新的"。如果它也只能
    命中这份缓存，按钮就成了摆设 —— 点下去拿回来的还是两秒前那份，用户看到的现象
    就是"点刷新没反应"。所以前端传 fresh=1 时这里必须真的去打一次 SSH。
    """
    now = time.time()
    with _SNAP_LOCK:
        if (not force and _SNAP["data"] is not None and _SNAP["out"] == out
                and now - _SNAP["ts"] < ttl):
            return _SNAP["data"]
    data = _remote().state(out, log_tail=80)
    with _SNAP_LOCK:
        _SNAP.update({"ts": time.time(), "out": out, "data": data})
    return data


def _force_refresh(value) -> bool:
    """解析 ?fresh= 参数。

    前端可能是 `fresh=1`，也可能是 `fresh=<时间戳>`（顺手当缓存钥匙用），
    所以只把"明确表示不要"的值当 False。
    """
    text = str(value if value is not None else "").strip().lower()
    return text not in ("", "0", "false", "no", "off", "none")



def _remote():
    """惰性建远端连接（只有打开 --remote 才会用到 paramiko）。"""
    global _RM
    if _RM is None:
        from remote import Remote

        _RM = Remote()
    return _RM


# --------------------------------------------------------------------- 工具
def _read_jsonl(path: str, limit: int = 5000) -> list[dict]:
    if not os.path.isfile(path):
        return []
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:]


def _read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:  # noqa: BLE001
        return {}


def _tail(path: str, lines: int = 80) -> list[str]:
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()[-lines:]
    except Exception:  # noqa: BLE001
        return []


def _alive() -> bool:
    proc = STATE.get("proc")
    return proc is not None and proc.poll() is None


def _dataset_profile(data_path: str, out_dir: str) -> dict:
    """数据画像：只用字符长度（不加载 tokenizer，秒回）。

    真 token 数在训练启动时由 train_sft 打印，这里要的是"一眼看规模对不对"。
    """
    cached = os.path.join(out_dir, "dataset.json")
    if not os.path.isfile(data_path):
        return {"exists": False, "path": data_path}
    mtime = os.path.getmtime(data_path)
    hit = _read_json(cached)
    if hit.get("mtime") == mtime and hit.get("rows"):
        return hit
    sources: Counter = Counter()
    ctx_len: list[int] = []
    ans_len: list[int] = []
    rows = 0
    with open(data_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows += 1
            sources[str(row.get("source") or "?")] += 1
            ctx_len.append(len(str(row.get("context") or "")))
            ans_len.append(len(str(row.get("response") or "")))
    def hist(values: list[int], bins: int = 10) -> dict:
        if not values:
            return {"bins": [], "counts": []}
        lo, hi = min(values), max(values)
        if hi == lo:
            hi = lo + 1
        step = max(1, (hi - lo) // bins)
        counts = [0] * bins
        for v in values:
            counts[min(bins - 1, (v - lo) // step)] += 1
        return {"bins": [lo + i * step for i in range(bins)], "counts": counts,
                "min": lo, "max": hi, "mean": sum(values) // max(1, len(values))}
    body = {"exists": True, "path": data_path, "rows": rows, "mtime": mtime,
            "sources": dict(sources.most_common()),
            "context_chars": hist(ctx_len), "answer_chars": hist(ans_len)}
    try:
        with open(cached, "w", encoding="utf-8") as fh:
            json.dump(body, fh, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass
    return body


# --------------------------------------------------------------------- API
app = FastAPI(title="δ-mem 训练面板")


@app.middleware("http")
async def _no_store(request: Request, call_next):
    """面板的所有响应都不许缓存。

    不加这条，浏览器会按启发式规则自行缓存 /api/state 的 JSON 和 /chart.svg，
    于是「刷新」拿到的还是上一轮的 body —— 前端再怎么加时间戳都没用。
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/api/state")
def api_state(out: str = "", fresh: str = ""):
    if REMOTE_MODE:
        # out 可能是本地绝对路径（--out 的默认值就是），必须先规整成
        # 相对 labs/dmem_train 的路径，否则远端路径会变成 /root/.../D:\...\out
        want = cloud_paths.out_rel(out or DEFAULT_OUT)
        try:
            return JSONResponse(_snapshot(want, force=_force_refresh(fresh)))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"running": False, "pid": None,
                                 "out_dir": want,
                                 "status": {"state": "offline", "error": str(exc)},
                                 "metrics": [], "eval": {}, "log": [str(exc)],
                                 "server_time": time.strftime("%H:%M:%S"),
                                 "remote": True})
    out_dir = out or DEFAULT_OUT
    status = _read_json(os.path.join(out_dir, "status.json"))
    metrics = _read_jsonl(os.path.join(out_dir, "metrics.jsonl"))
    eval_body = _read_json(os.path.join(out_dir, "eval.json"))
    running = _alive()
    if not running and status.get("state") == "running" and metrics:
        # 进程没了但状态还写着 running：被 kill -9 或 shell 断了
        status["state"] = "stopped"
    return JSONResponse({
        "running": running,
        "pid": STATE["proc"].pid if _alive() else None,
        "out_dir": out_dir,
        "argv": STATE.get("argv") or status.get("argv") or [],
        "status": status,
        "metrics": metrics,
        "eval": eval_body,
        "log": _tail(STATE.get("log_path") or "", 80),
        "server_time": time.strftime("%H:%M:%S"),
    })


@app.get("/api/dataset")
def api_dataset(data: str = "", out: str = ""):
    if REMOTE_MODE:
        try:
            return JSONResponse(_remote().dataset(data or "sft.jsonl"))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"exists": False, "path": data, "error": str(exc)})
    data_path = data or os.path.join(HERE, "data", "sft.jsonl")
    return JSONResponse(_dataset_profile(data_path, out or DEFAULT_OUT))


@app.get("/api/files")
def api_files(folder: str = ""):
    if REMOTE_MODE:
        try:
            return JSONResponse({"items": _remote().files(), "roots": ["remote"]})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"items": [], "roots": [f"远端不可用: {exc}"]})
    """列出可选的数据文件：labs/dmem_train/data 与模块的 .dmem_work（都只要 .jsonl）。

    返回**绝对路径**，前端直接用，省得在前端拼路径分隔符（Windows/Linux 混跑时最容易错）。
    """
    roots = [folder] if folder else [
        os.path.join(HERE, "data"),        os.path.join(HERE, ".dmem_work"),
    ]
    items = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            if not name.endswith((".jsonl", ".json")):
                continue
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                continue
            items.append({"name": name, "path": os.path.abspath(path),
                          "dir": os.path.basename(root),
                          "size": os.path.getsize(path),
                          "mtime": time.strftime("%m-%d %H:%M",
                                                 time.localtime(os.path.getmtime(path)))})
    items.sort(key=lambda x: -x["size"])
    return JSONResponse({"items": items, "roots": roots})


@app.post("/api/start")
async def api_start(request: Request):
    body = await request.json()
    if REMOTE_MODE:
        return _remote_start(body)
    if _alive():
        return JSONResponse({"ok": False, "error": "已经在跑了"}, status_code=409)

    data = str(body.get("data") or os.path.join(HERE, "data", "sft.jsonl"))
    out_dir = str(body.get("out") or DEFAULT_OUT)
    if not os.path.isfile(data):
        return JSONResponse({"ok": False, "error": f"数据不存在：{data}"},
                            status_code=400)
    argv = [sys.executable, os.path.join(HERE, "train_sft.py"),
            "--data", data, "--out", out_dir]
    for key, flag in (("model", "--model"), ("preset", "--preset"),
                      ("rank", "--rank"), ("n_states", "--n-states"),
                      ("chunk", "--chunk"), ("alpha", "--alpha"),
                      ("layers", "--layers"), ("epochs", "--epochs"),
                      ("accum", "--accum"), ("lr", "--lr"),
                      ("context_len", "--context-len"),
                      ("answer_len", "--answer-len"), ("window", "--window"),
                      ("max_steps", "--max-steps"), ("clip", "--clip"),
                      ("holdout", "--holdout"), ("seed", "--seed")):
        value = body.get(key)
        if value in (None, "", False):
            continue
        if isinstance(value, bool):
            argv.append(flag)
            continue
        argv += [flag, str(value)]
    if body.get("dry_run"):
        argv.append("--dry-run")

    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, "train.log")
    log = open(log_path, "a", encoding="utf-8", buffering=1)
    log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} "
              f"{shlex.join(argv)}\n")
    log.flush()
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    proc = subprocess.Popen(argv, cwd=HERE, stdout=log, stderr=subprocess.STDOUT,
                            env=env, start_new_session=(os.name != "nt"))
    STATE.update({"proc": proc, "log_path": log_path, "argv": argv[1:],
                  "started": time.time()})
    return JSONResponse({"ok": True, "pid": proc.pid, "argv": argv[1:],
                         "log": log_path})


#: 启动临界区：连点两下不能起两个训练
_LAUNCH_GATE = threading.Lock()


def _remote_start(body: dict) -> JSONResponse:
    """远端启动：把面板里的参数翻译成 train_sft.py 的命令行参数。

    为什么需要三重阳止（按从粗到细）：
      1. 前端：点下后按钮立刻锁 10 秒，正常人手速根本点不到第二次；
      2. 这把锁：即使两个请求同时到，也只能有一个进"检查→启动"临界区；
      3. launch 之后再数一次进程数，多出来的直接杀掉（兜底，防 ssh 慢导致的漏判）。
    """
    if not _LAUNCH_GATE.acquire(blocking=False):
        return JSONResponse({"ok": False, "error": "上一次启动请求还在处理，稍等 2 秒再点"},
                            status_code=429)
    try:
        data_name = posixpath.basename(str(body.get("data") or "sft.jsonl")
                                       .replace("\\", "/")) or "sft.jsonl"
        remote_data = f"data/{data_name}"
        out_dir = cloud_paths.out_rel(body.get("out") or "out")
        # 只传"额外参数"：--data / --out 由云端 launch.sh 负责
        argv: list[str] = ["--model",
                           cloud_paths.model_rel(body.get("model") or DEFAULT_MODEL)]
        for key, flag in (("preset", "--preset"), ("rank", "--rank"),
                          ("n_states", "--n-states"), ("chunk", "--chunk"),
                          ("alpha", "--alpha"), ("layers", "--layers"),
                          ("epochs", "--epochs"), ("accum", "--accum"),
                          ("lr", "--lr"), ("context_len", "--context-len"),
                          ("answer_len", "--answer-len"), ("window", "--window"),
                          ("max_steps", "--max-steps"), ("clip", "--clip"),
                          ("holdout", "--holdout"),
                          ("save_every", "--save-every"), ("seed", "--seed")):
            value = body.get(key)
            if value in (None, "", False):
                continue
            argv += [flag, str(value)]
        if body.get("dry_run"):
            argv.append("--dry-run")
        try:
            result = _remote().start(argv, out_dir, data=remote_data)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        # 不要再"清理多余进程"：之前那段 post-check 用 pgrep 拿到的是 bash
        # 包装进程 pid，把真正的 python 训练进程 kill -9 了 —— 这就是
        # "点启动后训练 2~3 秒消失"的根因。已永久删除。
        if not result.get("ok"):
            return JSONResponse(result, status_code=409 if result.get("pid")
                                else 500)
        return JSONResponse(result)
    finally:
        _LAUNCH_GATE.release()


@app.post("/api/stop")
def api_stop():
    if REMOTE_MODE:
        try:
            return JSONResponse(_remote().stop())
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    proc = STATE.get("proc")
    if proc is None or proc.poll() is not None:
        return JSONResponse({"ok": False, "error": "没有在跑的训练"}, status_code=409)
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    time.sleep(0.8)
    return JSONResponse({"ok": True, "state": "stopped"})


@app.get("/api/runs")
def api_runs(fresh: str = ""):
    """所有运行记录（自动发现），前端据此选中"正在跑的那一个"。

    本地模式本来就是每次都读文件；远端模式的 runs() 每次都是现打 SSH 列目录，
    没有缓存，所以 fresh 在这里天生就满足 —— 参数照收，只是不需要额外处理。
    """
    if REMOTE_MODE:
        try:
            return JSONResponse(_remote().runs())
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)
    rows = []
    base = DEFAULT_OUT
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            status_path = os.path.join(base, name, "status.json")
            if not os.path.isfile(status_path):
                continue
            st = _read_json(status_path)
            ev = _read_json(os.path.join(base, name, "eval.json"))
            rows.append({"out": f"out/{name}", "step": st.get("step"),
                         "total": st.get("total"), "progress": st.get("progress"),
                         "loss": st.get("loss"), "eta_s": st.get("eta_s"),
                         "elapsed_s": st.get("elapsed_s"), "state": st.get("state"),
                         "updated_at": st.get("updated_at"),
                         "mtime": os.path.getmtime(status_path),
                         "gap": ev.get("gap"), "no_context": ev.get("no_context"),
                         "with_state": ev.get("with_state")})
    rows.sort(key=lambda r: -r["mtime"])
    return JSONResponse(rows[:20])


def _svg_loss(metrics: list[dict], width: int = 1100, height: int = 190) -> str:
    """在服务端把 loss 画成 SVG 字符串。

    为什么不用前端 canvas/SVG：浏览器那边的渲染反复出问题（白屏/不画）。
    这里直接吐 `<svg>` 字节流，前端只用 `<img src="/chart.svg">`，浏览器原生渲染，
    没有任何 JS 参与，能显示文字就一定能显示图。
    """
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
            f'<rect width="{width}" height="{height}" fill="#0f1218"/>')
    pts = [(m.get("step"), m.get("loss")) for m in (metrics or [])
           if m.get("loss") is not None]
    if len(pts) < 2:
        return (head + '<text x="16" y="30" fill="#7c8598" font-size="14" '
                'font-family="monospace">暂无 loss 数据（训练开始后刷新）</text>'
                '</svg>')
    ys = [float(v) for _, v in pts]
    xs = [int(s or i) for i, (s, _) in enumerate(pts)]
    lo, hi = min(ys), max(ys)
    if hi - lo < 1e-6:
        hi, lo = lo + 1, lo - 1
    pad = (hi - lo) * 0.10
    lo -= pad
    hi += pad
    L, R, T, B = 56, 14, 12, 22
    x0, x1 = xs[0], max(xs[-1], xs[0] + 1)
    body = []
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        y = T + (height - T - B) * (1 - (v - lo) / (hi - lo))
        body.append(f'<line x1="{L}" y1="{y:.1f}" x2="{width - R}" '
                    f'y2="{y:.1f}" stroke="#1b2230" stroke-width="1"/>')
        body.append(f'<text x="4" y="{y + 4:.1f}" fill="#66708a" '
                    f'font-size="11" font-family="monospace">{v:.2f}</text>')
    coords = []
    for s, v in pts:
        x = L + (s - x0) / (x1 - x0) * (width - L - R)
        y = T + (height - T - B) * (1 - (v - lo) / (hi - lo))
        coords.append(f"{x:.1f},{y:.1f}")
    body.append(f'<polyline fill="none" stroke="#3ddc84" stroke-width="2" '
                f'stroke-linejoin="round" points="{" ".join(coords)}"/>')
    body.append(f'<text x="{L}" y="{height - 6}" fill="#66708a" font-size="11" '
                f'font-family="monospace">{x0}</text>')
    body.append(f'<text x="{width - R - 34}" y="{height - 6}" fill="#66708a" '
                f'font-size="11" font-family="monospace">{x1}</text>')
    body.append(f'<text x="{L + 8}" y="{T + 14}" fill="#9aa4b8" font-size="11" '
                f'font-family="monospace">loss {ys[0]:.3f} -&gt; '
                f'{ys[-1]:.3f}   ({len(ys)} 点, 最低 {lo + pad:.3f})</text>')
    return head + "".join(body) + "</svg>"


@app.get("/chart.svg")
def chart_svg(out: str = "", fresh: str = ""):
    """服务端渲染的 loss 图（浏览器只管 <img> 显示，不跑 JS）。

    正常轮询走 2 秒快照缓存（和 /api/state 共用同一份，几乎不额外打 SSH）；
    手动刷新带 fresh=1 时重新拉一次，保证图和新数字是同一时刻的。
    """
    from fastapi import Response

    target = out or DEFAULT_OUT
    metrics: list[dict] = []
    try:
        if REMOTE_MODE:
            metrics = _snapshot(target, force=_force_refresh(fresh)).get("metrics") or []
        else:
            base = os.path.join(os.path.abspath(target))
            metrics = _read_jsonl(os.path.join(base, "metrics.jsonl"))
    except Exception as exc:  # noqa: BLE001
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="190">'
               f'<rect width="1100" height="190" fill="#0f1218"/>'
               f'<text x="16" y="30" fill="#ff8a8a" font-size="13" '
               f'font-family="monospace">读取失败: {exc}</text></svg>')
        return Response(content=svg, media_type="image/svg+xml",
                        headers={"Cache-Control": "no-store"})
    return Response(content=_svg_loss(metrics), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse)
def index():
    # 前端文件位置按"用户实际摆法"多点查找（面板在 labs/dmem_train 下，
    # 临时工作区在 labs/dmem_train/.dmem_work/，不假设它在模块根）。
    candidates = [
        os.path.join(HERE, "panel.html"),
        os.path.join(HERE, ".dmem_work", "panel.html"),
        os.path.join(os.path.dirname(os.path.dirname(HERE)), ".dmem_work", "panel.html"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as fh:
                return HTMLResponse(fh.read())
    return HTMLResponse(PAGE)


# --------------------------------------------------------------------- 页面
PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>δ-mem 训练面板</title>
<style>
 :root{--bg:#0f1115;--card:#171a21;--line:#262b36;--fg:#e6e8ee;--dim:#8b93a7;
       --ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--accent:#60a5fa}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--fg);
      font:14px/1.5 "Microsoft YaHei",system-ui,sans-serif}
 header{display:flex;align-items:center;gap:14px;padding:12px 18px;
        border-bottom:1px solid var(--line);background:var(--card)}
 h1{font-size:16px;margin:0;font-weight:600}
 .dot{width:9px;height:9px;border-radius:50%;background:var(--dim)}
 .dot.run{background:var(--ok);box-shadow:0 0 8px var(--ok);animation:blink 1.4s infinite}
 @keyframes blink{50%{opacity:.35}}
 main{display:grid;grid-template-columns:320px 1fr;gap:14px;padding:14px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
 .card h2{font-size:13px;margin:0 0 10px;color:var(--dim);font-weight:600;
          letter-spacing:.04em;text-transform:uppercase}
 label{display:block;font-size:12px;color:var(--dim);margin:8px 0 3px}
 input,select{width:100%;background:#0d0f13;border:1px solid var(--line);
              color:var(--fg);border-radius:6px;padding:6px 8px;font-size:13px}
 .row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
 button{cursor:pointer;border:0;border-radius:7px;padding:9px 14px;
        font-size:13px;font-weight:600;color:#0b0d11}
 .primary{background:var(--ok)} .danger{background:var(--bad);color:#fff}
 button:disabled{opacity:.45;cursor:not-allowed}
 .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}
 .kpi{background:#12151b;border:1px solid var(--line);border-radius:8px;padding:10px}
 .kpi .v{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
 .kpi .k{font-size:11px;color:var(--dim)}
 .bar{height:8px;background:#0d0f13;border-radius:6px;overflow:hidden;margin:10px 0 4px}
 .bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,#60a5fa,#4ade80);
        transition:width .4s}
 canvas{width:100%;display:block}
 .log{height:190px;overflow:auto;background:#0a0c10;border:1px solid var(--line);
      border-radius:8px;padding:8px;font:12px/1.45 Consolas,monospace;
      white-space:pre-wrap;color:#aeb6c8}
 .flex{display:flex;gap:10px;align-items:center}
 .muted{color:var(--dim);font-size:12px}
 .tag{display:inline-block;padding:1px 7px;border-radius:99px;background:#1d2330;
      color:var(--accent);font-size:11px;margin-left:6px}
</style></head><body>
<header>
  <div class="dot" id="dot"></div><h1>δ-mem 训练面板</h1>
  <span class="muted" id="hdr">未连接</span>
  <span class="tag" id="hdrpid"></span>
</header>
<main>
  <div>
    <div class="card">
      <h2>启动训练</h2>
      <label>数据文件</label>
      <select id="data"></select>
      <label>输出目录</label>
      <input id="out" value="">
      <div class="row">
        <div><label>rank</label><input id="rank" value="64"></div>
        <div><label>chunk</label><input id="chunk" value="16"></div>
      </div>
      <div class="row">
        <div><label>epochs</label><input id="epochs" value="1"></div>
        <div><label>accum</label><input id="accum" value="2"></div>
      </div>
      <div class="row">
        <div><label>lr</label><input id="lr" value="2e-4"></div>
        <div><label>context_len</label><input id="context_len" value="768"></div>
      </div>
      <div class="row">
        <div><label>layers(空=全层)</label><input id="layers" value=""></div>
        <div><label>max_steps(0=不限)</label><input id="max_steps" value="0"></div>
      </div>
      <div class="flex" style="margin-top:12px">
        <button class="primary" id="btnStart">启动</button>
        <button class="danger" id="btnStop" disabled>停止</button>
        <button id="btnDry" style="background:#2b3242;color:#cfd6e6">干跑 2 步</button>
      </div>
      <div class="muted" id="msg" style="margin-top:8px"></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h2>数据画像</h2>
      <div id="dsInfo" class="muted">读取中…</div>
      <div class="chart" id="cvData" style="height:84px;margin-top:8px"></div>    </div>
  </div>
  <div>
    <div class="kpis">
      <div class="kpi"><div class="v" id="kLoss">—</div><div class="k">loss</div></div>
      <div class="kpi"><div class="v" id="kStep">—</div><div class="k">step / total</div></div>
      <div class="kpi"><div class="v" id="kEta">—</div><div class="k">ETA</div></div>
      <div class="kpi"><div class="v" id="kGap">—</div><div class="k">留出集 gap</div></div>
    </div>
    <div class="card">
      <div class="flex" style="justify-content:space-between">
        <h2 style="margin:0">loss 曲线</h2>
        <span class="muted" id="curveInfo"></span>
      </div>
      <div class="bar"><i id="prog"></i></div>
      <div class="chart" id="cvLoss" style="height:140px"></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h2>学习率</h2>
      <div class="chart" id="cvLr" style="height:72px"></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h2>日志</h2>
      <div class="log" id="log"></div>
    </div>
  </div>
</main>
<script>
const $ = id => document.getElementById(id);
let dataPath = "";

function fmt(n, d=3){ return (n===null||n===undefined)?"—":Number(n).toFixed(d); }
function fmtTime(s){
  if(s===null||s===undefined) return "—";
  s = Math.max(0, Math.round(s));
  const h=Math.floor(s/3600), m=Math.floor(s%3600/60), ss=s%60;
  return h? `${h}h${String(m).padStart(2,"0")}m` : `${m}m${String(ss).padStart(2,"0")}s`;
}

// ---- 极简折线图（canvas 手画，无依赖）----
function line(canvas, series, opts){
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || (canvas.parentElement ? canvas.parentElement.clientWidth : 0) || 640;
  const h = canvas.height;
  canvas.width = w*dpr; canvas.height = h*dpr;
  const c = canvas.getContext("2d");
  c.setTransform(dpr,0,0,dpr,0,0);
  c.clearRect(0,0,w,h);
  const pad = {l:44,r:10,t:10,b:18};
  const W = w-pad.l-pad.r, H = h-pad.t-pad.b;
  const all = series.flatMap(s=>s.y).filter(v=>v!==null&&isFinite(v));
  if(!all.length){
    c.fillStyle="#5b6377"; c.font="12px system-ui";
    c.fillText("暂无数据", pad.l+8, pad.t+18); return;
  }
  let lo = Math.min(...all), hi = Math.max(...all);
  if(hi-lo < 1e-9){ hi = lo + 1; lo -= 1; }
  const padY = (hi-lo)*0.08; lo-=padY; hi+=padY;
  const xs = series.flatMap(s=>s.x);
  const x0 = Math.min(...xs), x1 = Math.max(...xs) || 1;
  const X = v => pad.l + (x1>x0 ? (v-x0)/(x1-x0) : 0.5)*W;
  const Y = v => pad.t + H - (v-lo)/(hi-lo)*H;
  // 网格
  c.strokeStyle="#1f2530"; c.lineWidth=1; c.font="11px system-ui"; c.fillStyle="#6b7385";
  for(let i=0;i<=4;i++){
    const v = lo + (hi-lo)*i/4, y = Y(v);
    c.beginPath(); c.moveTo(pad.l,y); c.lineTo(pad.l+W,y); c.stroke();
    c.fillText(v.toFixed(2), 4, y+4);
  }
  // 线
  series.forEach(s=>{
    c.beginPath(); c.strokeStyle=s.color; c.lineWidth=1.8;
    s.y.forEach((v,i)=>{
      if(v===null||!isFinite(v)) return;
      const x=X(s.x[i]), y=Y(v);
      i? c.lineTo(x,y) : c.moveTo(x,y);
    });
    c.stroke();
    if(s.fill){
      c.lineTo(X(s.x[s.x.length-1]), pad.t+H); c.lineTo(X(s.x[0]), pad.t+H);
      c.closePath(); c.fillStyle=s.fill; c.fill();
    }
  });
  c.fillStyle="#6b7385";
  c.fillText(String(x0), pad.l, h-4);
  const label = String(x1);
  c.fillText(label, pad.l+W-c.measureText(label).width, h-4);
}

// ---- 柱状图（数据分布）----
function bars(canvas, counts, labels){
  const dpr = window.devicePixelRatio||1;
  const w = canvas.clientWidth || (canvas.parentElement ? canvas.parentElement.clientWidth : 0) || 640;
  const h = canvas.height;
  canvas.width=w*dpr; canvas.height=h*dpr;
  const c = canvas.getContext("2d"); c.setTransform(dpr,0,0,dpr,0,0);
  c.clearRect(0,0,w,h);
  if(!counts || !counts.length){ return; }
  const max = Math.max(...counts) || 1;
  const bw = w/counts.length;
  counts.forEach((v,i)=>{
    const bh = (v/max)*(h-16);
    c.fillStyle = i%2 ? "#3b82f6" : "#60a5fa";
    c.fillRect(i*bw+2, h-bh-2, bw-4, bh);
  });
  c.fillStyle="#6b7385"; c.font="10px system-ui";
  if(labels && labels.length) c.fillText(labels[0], 2, h-2);
}

// ---- 轮询 ----
// 单飞：上一轮还没回来就绝不再发一条。慢后端（远端一次 SSH 往返 3~8 秒）下
// setInterval(2000) 会把请求堆成队，页面就永远停在旧数据上。
let _refreshing = false;
async function refresh(){
  if(_refreshing) return;
  _refreshing = true;
  try{
    const r = await fetch(`/api/state?out=${encodeURIComponent($("out").value)}`,
                          {cache:"no-store"});
    const s = await r.json();
    $("dot").className = "dot" + (s.running ? " run" : "");
    $("hdr").textContent = s.running ? `训练中 PID ${s.pid}` :
        (s.status.state ? `状态 ${s.status.state}` : "未连接");
    $("hdrpid").textContent = s.server_time || "";
    $("btnStart").disabled = false;   // 永不锁死：宁可让用户点到，由后端报"已在跑"
    $("btnStop").disabled = !s.running;

    const st = s.status || {};
    $("kLoss").textContent = fmt(st.loss);
    $("kStep").textContent = `${st.step||0} / ${st.total||0}`;
    $("kEta").textContent = st.state==="finished" ? "完成" : fmtTime(st.eta_s);
    $("prog").style.width = `${((st.progress||0)*100).toFixed(1)}%`;
    const ev = s.eval || {};
    $("kGap").textContent = ev.gap!==undefined ? Number(ev.gap).toFixed(3) : "—";
    if(ev.gap!==undefined){
      $("curveInfo").textContent =
        `no-context ${Number(ev.no_context).toFixed(3)} → with-state ${Number(ev.with_state).toFixed(3)}`;
    } else {
      $("curveInfo").textContent = st.elapsed_s ? `已用 ${fmtTime(st.elapsed_s)}` : "";
    }

    const m = s.metrics || [];
    if(m.length){
      line($("cvLoss"), [{
        x: m.map(p=>p.step), y: m.map(p=>p.loss),
        color:"#4ade80", fill:"rgba(74,222,128,.08)"
      }]);
      line($("cvLr"), [{x: m.map(p=>p.step), y: m.map(p=>p.lr), color:"#fbbf24"}]);
    } else {
      line($("cvLoss"), []); line($("cvLr"), []);
    }
    const logEl = $("log");
    const atBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight-30;
    logEl.textContent = (s.log||[]).join("\n");
    if(atBottom) logEl.scrollTop = logEl.scrollHeight;
  }catch(e){
    $("hdr").textContent = "面板与后端失联：" + e.message;
  }finally{
    _refreshing = false;
  }
}

async function loadData(){
  const d = await (await fetch(`/api/dataset?data=${encodeURIComponent(dataPath)}&out=${encodeURIComponent($("out").value)}`)).json();
  if(!d.exists){ $("dsInfo").textContent = "数据文件不存在：" + d.path; bars($("cvData"), []); return; }
  const src = Object.entries(d.sources||{}).map(([k,v])=>`${k}: ${v}`).join(" · ");
  $("dsInfo").innerHTML = `共 <b>${d.rows}</b> 条样本<br>${src}<br>
    context 字符 p50≈${d.context_chars.mean}，answer 字符 p50≈${d.answer_chars.mean}`;
  bars($("cvData"), d.context_chars.counts, [String(d.context_chars.min), String(d.context_chars.max)]);
}

async function loadFiles(){
  const f = await (await fetch(`/api/files`)).json();
  const sel = $("data");
  sel.innerHTML = "";
  (f.items||[]).forEach(it=>{
    const o = document.createElement("option");
    o.value = it.path;
    o.textContent = `[${it.dir}] ${it.name}  (${(it.size/1024).toFixed(0)}KB, ${it.mtime})`;
    sel.appendChild(o);
  });
  if(!(f.items||[]).length){
    const o = document.createElement("option");
    o.value = ""; o.textContent = "（没找到 .jsonl，先跑 build_data.py）";
    sel.appendChild(o);
  }
  dataPath = sel.value || "";
  sel.onchange = () => { dataPath = sel.value; loadData(); };
  loadData();
}

function payload(dry){
  const p = {data: dataPath, out: $("out").value};
  ["rank","chunk","epochs","accum","lr","context_len","layers","max_steps"]
    .forEach(k=>{ const v = $(k).value.trim(); if(v!=="") p[k]=v; });
  if(dry) p.dry_run = true;
  return p;
}

let launching = false;
async function start(dry){
  if(launching) return;                      // 连点保护（第一道）
  launching = true;
  $("btnStart").disabled = true;
  $("btnStart").textContent = dry ? "干跑中…" : "启动中…";
  $("msg").textContent = dry ? "启动干跑…" : "启动训练…";
  try{
    const r = await fetch("/api/start", {method:"POST",
        headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload(dry))});
    const j = await r.json();
    $("msg").textContent = j.ok ? `已启动 PID ${j.pid}`
        : ("失败：" + (j.error || r.status));
  }catch(e){
    $("msg").textContent = "请求失败：" + e.message;
  }finally{
    setTimeout(()=>{                        // 10 秒后才放开，够后端把进程拉起来
      launching = false;
      $("btnStart").disabled = false;
      $("btnStart").textContent = "启动";
      refresh();
    }, 10000);
  }
}

$("btnStart").onclick = ()=>start(false);
$("btnDry").onclick = ()=>start(true);
$("btnStop").onclick = async ()=>{
  if(!confirm("确定停止训练？已保存的 step 权重还在。")) return;
  const r = await fetch("/api/stop", {method:"POST"});
  const j = await r.json();
  $("msg").textContent = j.ok ? "已停止" : ("停止失败：" + j.error);
  setTimeout(refresh, 600);
};
// ---- 用 SVG 重画：canvas 在部分环境（dpr/0 宽）会白屏，SVG 不会 ----
line = function(el, series){
  const w = el.clientWidth || 640;
  const h = parseInt(el.style.height || "200", 10) || 200;
  const pts0 = (series || []).flatMap(s => (s.y || []).filter(v => v !== null && isFinite(v)));
  if(!pts0.length){
    el.innerHTML = `<div style="color:#5b6377;font-size:12px;padding:14px 4px">
      暂无数据（训练跑起来后这里会出现曲线）</div>`;
    return;
  }
  let lo = Math.min(...pts0), hi = Math.max(...pts0);
  if(hi - lo < 1e-9){ hi = lo + 1; lo -= 1; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const xs = (series || []).flatMap(s => s.x || []);
  const x0 = Math.min(...xs), x1 = Math.max(...xs) || 1;
  const L = 46, R = 10, T = 10, B = 18;
  const X = v => L + (x1 > x0 ? (v - x0) / (x1 - x0) : 0.5) * (w - L - R);
  const Y = v => T + (h - T - B) * (1 - (v - lo) / (hi - lo));
  let out = "";
  for(let i = 0; i <= 4; i++){
    const v = lo + (hi - lo) * i / 4, y = Y(v);
    out += `<line x1="${L}" y1="${y.toFixed(1)}" x2="${w - R}" y2="${y.toFixed(1)}"
            stroke="#1f2530" stroke-width="1"/>`
         + `<text x="2" y="${(y + 4).toFixed(1)}" fill="#6b7385"
            font-size="11" font-family="monospace">${v.toFixed(2)}</text>`;
  }
  (series || []).forEach(s => {
    const pts = (s.y || []).map((v, i) => [X(s.x[i]), Y(v)])
                            .filter(p => isFinite(p[1]));
    if(!pts.length) return;
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    out += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.8"/>`;
  });
  out += `<text x="${L}" y="${h - 4}" fill="#6b7385" font-size="11">${x0}</text>`
       + `<text x="${w - R - 30}" y="${h - 4}" fill="#6b7385" font-size="11">${x1}</text>`;
  el.innerHTML = `<svg width="100%" height="${h}" style="display:block">${out}</svg>`;
};

bars = function(el, counts, labels){
  const w = el.clientWidth || 640;
  const h = parseInt(el.style.height || "120", 10) || 120;
  if(!counts || !counts.length){
    el.innerHTML = `<div style="color:#5b6377;font-size:12px;padding:14px 4px">暂无分布数据</div>`;
    return;
  }
  const max = Math.max(...counts) || 1;
  const bw = w / counts.length;
  let out = "";
  counts.forEach((v, i) => {
    const bh = (v / max) * (h - 18);
    out += `<rect x="${(i * bw + 2).toFixed(1)}" y="${(h - bh - 2).toFixed(1)}"
            width="${Math.max(1, bw - 4).toFixed(1)}" height="${bh.toFixed(1)}"
            fill="${i % 2 ? "#3b82f6" : "#60a5fa"}"/>`;
  });
  if(labels && labels.length){
    out += `<text x="2" y="${h - 4}" fill="#6b7385" font-size="10">${labels[0]}</text>`;
  }
  el.innerHTML = `<svg width="100%" height="${h}" style="display:block">${out}</svg>`;
};

window.addEventListener("resize", ()=>refresh());
// 记住「输出目录」与数据选择：刷新后必须还指向同一个 run，否则面板会看起来"空了"
const LS_OUT = "dmem.out", LS_DATA = "dmem.data";
const savedOut = localStorage.getItem(LS_OUT);
const urlOut = new URLSearchParams(location.search).get("out");
$("out").value = urlOut || savedOut || "";
$("out").addEventListener("input", () => localStorage.setItem(LS_OUT, $("out").value));
try {
  loadFiles();
  (async function loop(){                 // 上一轮结束才排下一轮
    await refresh();
    setTimeout(loop, 2000);
  })();
} catch (e) {
  document.body.insertAdjacentHTML("afterbegin",
    `<div style="background:#7f1d1d;color:#fff;padding:10px 14px;font:13px monospace">
       JS 初始化失败：${e && e.message ? e.message : e}（按 Ctrl+F5 强刷）</div>`);
}
</script></body></html>
"""


def main() -> int:
    global DEFAULT_MODEL, DEFAULT_OUT, REMOTE_MODE

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--remote", action="store_true",
                    help="训练跑在 AutoDL（凭据读 labs/autoDL/），本地面板只做监控与启停")
    ap.add_argument("--model", default="",
                    help="后端 backbone，相对模块根（默认 models/Qwen3-8B；"
                         "本机验管道可用 models/Qwen3-0.6B）")
    args = ap.parse_args()

    REMOTE_MODE = bool(args.remote)
    if args.model:
        DEFAULT_MODEL = cloud_paths.model_rel(args.model)
    if REMOTE_MODE:
        # 远端模式：out 是**相对 labs/dmem_train** 的路径，不落地到本地磁盘
        DEFAULT_OUT = cloud_paths.out_rel(args.out)
    else:
        DEFAULT_OUT = os.path.abspath(args.out)
        os.makedirs(DEFAULT_OUT, exist_ok=True)
    STATE["log_path"] = os.path.join(HERE, "train.log") if REMOTE_MODE \
        else os.path.join(DEFAULT_OUT, "train.log")

    try:
        import uvicorn
    except Exception:  # noqa: BLE001
        print("需要 uvicorn：pip install uvicorn")
        return 2
    print(f"δ-mem 训练面板： http://{args.host}:{args.port}")
    print(f"输出目录：{DEFAULT_OUT}"
          + ("（远端，相对 labs/dmem_train）" if REMOTE_MODE else ""))
    if REMOTE_MODE:
        print(f"远端根：{cloud_paths.remote_root()}   模型：{DEFAULT_MODEL}")
    if args.host == "0.0.0.0":
        print("AutoDL 提示：本机执行 ssh -L %d:127.0.0.1:%d -p <端口> root@<实例> "
              "再打开 http://127.0.0.1:%d" % (args.port, args.port, args.port))
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
