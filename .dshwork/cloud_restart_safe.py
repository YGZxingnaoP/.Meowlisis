# -*- coding: utf-8 -*-
"""安全重启云端服务：先杀（前台、等它返回），再起（fire-and-forget、命令里不含 sleep）。

用法（在 .vendor/.MeowLLM 下）：
    D:\.Meowlisis\runtime\311\python.exe ..\..\.dshwork\cloud_restart_safe.py
"""

from __future__ import annotations

import os
import sys
import time

ROOT = r"D:\.Meowlisis\.vendor\.MeowLLM"
sys.path.insert(0, os.path.join(ROOT, "labs", "dmem_train"))

import cloud  # noqa: E402
import cloud_paths  # noqa: E402

root = cloud_paths.remote_root()
cl = cloud.Cloud(quiet=True)
try:
    code, out = cl.run("pkill -f '[m]eowllm.server.app' ; sleep 1 ; "
                       "pgrep -fc '[m]eowllm.server.app' || true", timeout=30)
    print("kill:", out.strip() or "(none)", flush=True)

    chan = cl.client.get_transport().open_session()
    try:
        chan.exec_command(
            f"cd {root} && setsid nohup bash serve.sh "
            "> /root/autodl-tmp/meowllm_server.log 2>&1 < /dev/null &")
        time.sleep(0.6)
    finally:
        try:
            chan.close()
        except Exception:  # noqa: BLE001
            pass
    print("start 已发", flush=True)

    for i in range(16):
        time.sleep(5)
        code = cl.run("curl -s -o /dev/null -w '%{http_code}' "
                      "http://127.0.0.1:18100/meowllm/control/health",
                      show=False)[1].strip()
        print(f"  {i + 1:02d} http={code}", flush=True)
        if code == "200":
            print("OK", flush=True)
            break
    if code != "200":
        print(cl.run("tail -8 /root/autodl-tmp/meowllm_server.log", show=False)[1])
finally:
    cl.close()
