#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用守护进程 v2：启动子进程（服务），子进程异常退出后 3 秒自动重启。
服务命令从同目录 guard.json 读取（"cmd": ["server/xx.py", "--port", "10095", ...]），
子进程解释器用本脚本的解释器(sys.executable)，保证云端/本地环境一致。
进程命令行只含 "guard.py"（不含服务名），因此 pkill 服务名不会误杀守护进程。

用法: nohup python guard.py > service.log 2>&1 &
收到 SIGTERM/SIGINT 时终止子进程并退出。
"""
import json
import os
import signal
import subprocess
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
_cfg_path = os.path.join(_here, "guard.json")

if not os.path.exists(_cfg_path):
    print("[guard] 缺少配置文件: {}".format(_cfg_path))
    sys.exit(2)

with open(_cfg_path, encoding="utf-8") as f:
    _data = json.load(f)

_cmd = [sys.executable] + list(_data.get("cmd", []))
if not _cmd[1:]:
    print("[guard] guard.json 中 cmd 为空")
    sys.exit(2)

child = None


def _term(_sig, _frm):
    global child
    if child is not None and child.poll() is None:
        try:
            child.terminate()
        except Exception:
            pass
    sys.exit(0)


signal.signal(signal.SIGTERM, _term)
signal.signal(signal.SIGINT, _term)

while True:
    print("[guard] 启动子进程: {}".format(" ".join(_cmd)), flush=True)
    child = subprocess.Popen(_cmd)
    try:
        code = child.wait()
    except KeyboardInterrupt:
        sys.exit(0)
    print("[guard] 子进程退出 code={}，3 秒后自动重启".format(code), flush=True)
    time.sleep(3)
