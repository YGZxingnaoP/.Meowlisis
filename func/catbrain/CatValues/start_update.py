# -*- coding: utf-8 -*-
# func/catbrain/CatValues/start_update.py
# 价值观更新触发接口（不含触发条件，仅作为统一入口）

from threading import Thread

from func.log.default_log import DefaultLog
from func.catbrain.CatValues.update_values import MeowUpdateValues


class MeowStartValuesUpdate:
    """价值观更新触发类：对外提供同步/异步两种触发入口"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.updater = MeowUpdateValues()

    def start(self, reason: str = "") -> bool:
        """同步触发价值观更新（阻塞直到流程结束，返回是否成功）"""
        return self.updater.update(reason)

    def start_async(self, reason: str = ""):
        """异步触发价值观更新（后台线程执行，不阻塞调用方）"""
        Thread(target=self._worker, args=(reason,), daemon=True).start()

    def _worker(self, reason: str):
        """异步执行工作线程（捕获异常避免线程静默失败）"""
        try:
            self.updater.update(reason)
        except Exception:
            self.log.exception("价值观异步更新异常")
