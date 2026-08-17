# -*- coding: utf-8 -*-
# func/pipeline/llm_values.py
# LLM → CatValues 价值观更新传递桥接

import threading
from threading import Thread

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class MeowLLMValuesBridge:
    """价值观更新桥接：接收各触发源的更新请求，去重防护并异步执行"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.Lock()
        self._updating = False

    def trigger_update(self, reason: str = ""):
        """触发价值观更新（已有更新进行中则跳过，异步执行不阻塞调用方）"""
        with self._lock:
            if self._updating:
                self.log.info(f"价值观更新进行中，跳过本次触发: {reason}")
                return
            self._updating = True
        self.log.info(f"价值观更新已触发: {reason}")
        Thread(target=self._worker, args=(reason,), daemon=True).start()

    def _worker(self, reason: str):
        """异步执行价值观更新，结束后恢复可触发状态"""
        try:
            from func.catbrain.CatValues.start_update import MeowStartValuesUpdate
            MeowStartValuesUpdate().start(reason)
        except Exception:
            self.log.exception("价值观更新异常")
        finally:
            with self._lock:
                self._updating = False
