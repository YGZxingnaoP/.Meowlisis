# -*- coding: utf-8 -*-
"""看云端返回体到底长什么样 + 服务日志里的回退原因。"""

from __future__ import annotations

import json
import os
import sys

MODULE = r"D:\.Meowlisis\.vendor\.MeowLLM"
sys.path.insert(0, os.path.join(MODULE, "labs", "dmem_train"))

import cloud  # noqa: E402
import cloud_paths  # noqa: E402

root = cloud_paths.remote_root()
cl = cloud.Cloud(quiet=True)
try:
    print("--- 日志里跟双流/回退有关的行 ---", flush=True)
    print(cl.run("grep -Ei 'dual|双流|plain|回退|上限' "
                 "/root/autodl-tmp/meowllm_server.log | tail -8", show=False)[1],
          flush=True)
    print("--- 最近一次请求的原始返回（截断） ---", flush=True)
    print(cl.run(
        "cd %s && grep -o '\"meowllm\":[^}]*}' /root/autodl-tmp/meowllm_server.log "
        "| tail -2" % root, show=False)[1], flush=True)
finally:
    cl.close()
