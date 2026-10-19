# -*- coding: utf-8 -*-
# scripts/_bootstrap.py
# 维护脚本公共启动：项目根入 sys.path + 日志降级
#
# 为什么需要日志降级：
#   应用运行时会独占 ./logs/log_<date>.txt，脚本再按 mode="a+" 打开会抛
#   PermissionError。这里在导入任何项目模块之前替换 DefaultLog 工厂：
#   真实 logger 可用就用，打不开就退回 stdout，脚本不会因此崩掉。

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _StdoutLogger:
    """最小可用 logger（只输出到 stdout）"""

    def getLogger(self):
        lg = logging.getLogger("dsh.script")
        if not lg.handlers:
            h = logging.StreamHandler(sys.stdout)
            h.setFormatter(logging.Formatter("    [log] %(message)s"))
            lg.addHandler(h)
            lg.setLevel(logging.INFO)
        return lg


def install_log_fallback():
    """把 DefaultLog 换成「能用真实 logger 就用，否则 stdout」的工厂"""
    try:
        import func.log.default_log as dl
    except Exception:
        return
    orig = getattr(dl, "DefaultLog", None)
    if orig is None:
        return

    state = {"failed": False}

    def factory(*a, **k):
        if state["failed"]:
            return _StdoutLogger()
        try:
            obj = orig(*a, **k)
            obj.getLogger()          # 触发文件句柄打开，提前暴露占用
            return obj
        except Exception:
            state["failed"] = True
            return _StdoutLogger()

    dl.DefaultLog = factory
