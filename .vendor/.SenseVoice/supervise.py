#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用守护进程：启动子进程（服务），子进程异常退出后 3 秒自动重启。
用法: python supervise.py <服务命令及其参数...>
例如: python supervise.py /root/miniconda3/bin/python server/sensevoice_server.py --port 10095 ...
收到 SIGTERM/SIGINT 时终止子进程并退出（配合 nohup 后台运行）。
"""
import signal
import subprocess
import sys
import time

cmd = sys.argv[1:]
if not cmd:
    print("用法: python supervise.py <cmd...>")
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
    print("[supervise] 启动子进程: {}".format(" ".join(cmd)), flush=True)
    child = subprocess.Popen(cmd)
    try:
        code = child.wait()
    except KeyboardInterrupt:
        sys.exit(0)
    print("[supervise] 子进程退出 code={}，3 秒后自动重启".format(code), flush=True)
    time.sleep(3)
