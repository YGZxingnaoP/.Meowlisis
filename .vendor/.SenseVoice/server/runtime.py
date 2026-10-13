# -*- coding: utf-8 -*-
# server/runtime.py - 运行时上下文：参数、模型、线程池、信号量、延迟打点

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor


class Runtime:
    """全局运行时：持有参数与共享资源，供会话/服务模块使用"""

    def __init__(self, args):
        self.args = args
        self.asr = None
        self.sv_model = None
        self.executor = ThreadPoolExecutor(max_workers=args.worker_threads)
        self.sem_asr = asyncio.Semaphore(args.concurrent_asr)
        self.sem_sv = asyncio.Semaphore(args.concurrent_sv)

    def shutdown(self):
        """释放线程池"""
        self.executor.shutdown(wait=False)

    def tick(self, event: str, extra: str = ""):
        """延迟打点（可选）：毫秒时间戳一行追加到 latency_log"""
        path = self.args.latency_log
        if not path:
            return
        try:
            clean = str(extra).replace("\t", " ").replace("\r", " ").replace("\n", " ")
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{int(time.time() * 1000)}\t{event}\t{clean}\n")
        except Exception:
            pass
