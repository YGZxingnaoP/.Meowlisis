# -*- coding: utf-8 -*-
"""一键把云端训练产物下载到本地 —— **落到与云端相同的相对结构**。

用法（双击 download_artifacts.bat 即可，或手跑）：
    python download_artifacts.py              # 下载最新一次完成的 run
    python download_artifacts.py out/run2     # 指定 run
    python download_artifacts.py --dest models/xxx   # 换目标目录（可选）

凭据：labs/autoDL/登录指令.txt + 密码.txt（已在 .gitignore 里）

为什么改成本地 `models/<run>/`（原来放 docs/output/<日期>/model/）
------------------------------------------------------------------
"云端结构严格符合本地"这条规则的落地方式就是**路径相对化**：

    云端  <REMOTE_ROOT>/labs/dmem_train/out/<run>/dmem.safetensors
    本地  .vendor/.MeowLLM/models/<run>/dmem.safetensors

于是 config.yml 里只写 `models/<run>/dmem.safetensors`，
下载完把 enabled 改成 true 就能用，不需要"再改一次路径"。
数据也回到 `labs/dmem_train/data/`，与云端同名同位置。

产物布局：
    models/<run>/     dmem.safetensors, dmem.step.safetensors,
                      eval.json, metrics.jsonl, status.json, train.log,
                      MANIFEST.json
    labs/dmem_train/data/  sft.jsonl, real_lo.jsonl, synth.jsonl
"""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import cloud_paths  # noqa: E402
from remote import Remote  # noqa: E402

REMOTE_BASE = cloud_paths.remote(cloud_paths.REL_TRAIN)


def default_dest(run: str) -> str:
    """run 目录名 -> 本地 `models/<run>` 绝对路径。"""
    name = posixpath.basename(str(run or "").rstrip("/")) or "run"
    return cloud_paths.local(posixpath.join(cloud_paths.REL_MODELS, name))


def sha1_of(path: str, limit: int = 32 << 20) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as fh:
        remain = limit
        while remain > 0:
            chunk = fh.read(min(1 << 20, remain))
            if not chunk:
                break
            digest.update(chunk)
            remain -= len(chunk)
    return digest.hexdigest()


def pick_run(rm: Remote, wanted: str) -> str:
    if wanted:
        return wanted
    rows = rm.runs()
    # 优先：已完成（有 eval.json）且 step 最大的
    done = [r for r in rows if r.get("gap") is not None]
    if done:
        done.sort(key=lambda r: -(r.get("step") or 0))
        return done[0]["out"]
    if rows:
        return rows[0]["out"]
    return cloud_paths.DEFAULT_RUN


def main() -> int:
    argv = [a for a in sys.argv[1:]]
    dest_override = ""
    if "--dest" in argv:
        idx = argv.index("--dest")
        if idx + 1 < len(argv):
            dest_override = argv[idx + 1]
            del argv[idx:idx + 2]
    wanted = argv[0] if argv else ""

    rm = Remote()
    try:
        run = cloud_paths.out_rel(pick_run(rm, wanted))
        dest = (os.path.abspath(dest_override) if dest_override
                else default_dest(run))
        data_dir = cloud_paths.local(cloud_paths.REL_DATA)

        st = rm.state(run, log_tail=5)
        s = st.get("status") or {}
        ev = st.get("eval") or {}
        print(f"run       : {run}")
        print(f"云端状态  : running={st.get('running')} state={s.get('state')} "
              f"step={s.get('step')}/{s.get('total')}")
        if ev:
            print(f"留出集    : no-context={ev.get('no_context')} "
                  f"with-state={ev.get('with_state')} gap={ev.get('gap')}")
        print(f"本地目标  : {dest}")
        print()

        wanted_files = [
            (f"{REMOTE_BASE}/{run}/dmem.safetensors", dest, "dmem.safetensors"),
            (f"{REMOTE_BASE}/{run}/dmem.step.safetensors", dest,
             "dmem.step.safetensors"),
            (f"{REMOTE_BASE}/{run}/eval.json", dest, "eval.json"),
            (f"{REMOTE_BASE}/{run}/metrics.jsonl", dest, "metrics.jsonl"),
            (f"{REMOTE_BASE}/{run}/status.json", dest, "status.json"),
            (f"{REMOTE_BASE}/{run}/train.log", dest, "train.log"),
            (f"{REMOTE_BASE}/data/sft.jsonl", data_dir, "sft.jsonl"),
            (f"{REMOTE_BASE}/data/real_lo.jsonl", data_dir, "real_lo.jsonl"),
            (f"{REMOTE_BASE}/data/synth.jsonl", data_dir, "synth.jsonl"),
        ]

        manifest = {"downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "run": run, "cloud_status": s, "cloud_eval": ev,
                    "local_dest": dest, "files": {}}
        ok = 0
        for remote_path, folder, name in wanted_files:
            rel = name
            local_path = os.path.join(folder, name)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            try:
                total = rm._sftp.stat(remote_path).st_size
            except Exception:
                print(f"  跳过（云端没有）  {rel}")
                continue
            began = time.time()
            try:
                rm._sftp.get(remote_path, local_path,
                             callback=_progress(rel, total, began))
            except Exception as exc:  # noqa: BLE001
                print(f"  失败 {rel}: {type(exc).__name__}: {exc}")
                continue
            size = os.path.getsize(local_path)
            digest = sha1_of(local_path)
            manifest["files"][rel] = {"bytes": size, "sha1": digest,
                                      "remote": remote_path,
                                      "local": local_path}
            print(f"  OK {rel:26s} {size / 1024 / 1024:7.2f} MB  "
                  f"{time.time() - began:.1f}s  sha1={digest[:12]}")
            ok += 1

        manifest_path = os.path.join(dest, "MANIFEST.json")
        os.makedirs(dest, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2, default=str)
        print()
        print(f"完成：{ok} 个文件 -> {dest}")
        print(f"清单：{manifest_path}")
        print()
        rel_weights = os.path.relpath(os.path.join(dest, "dmem.safetensors"),
                                      cloud_paths.MODULE_ROOT).replace("\\", "/")
        print("下一步：把 config.yml 的 memory.delta_mem.weights 指向")
        print(f"  {rel_weights}     （相对 .vendor/.MeowLLM/ —— 云端同样可写这个值）")
        print("并把 memory.delta_mem.enabled 改成 true，然后重启 MeowLLM。")
        return 0 if ok else 1
    finally:
        rm.close()


def _progress(rel: str, total: int, began: float):
    last = {"t": 0.0}

    def cb(done, _total):
        now = time.time()
        if now - last["t"] < 1.0 and done < total:
            return
        last["t"] = now
        pct = done / max(1, total) * 100
        speed = done / max(1e-6, now - began) / 1024 / 1024
        print(f"    {rel}: {pct:5.1f}%  {done / 1048576:6.1f}MB / "
              f"{total / 1048576:.1f}MB  {speed:.1f}MB/s")

    return cb


if __name__ == "__main__":
    raise SystemExit(main())
