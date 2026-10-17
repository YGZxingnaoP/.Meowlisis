# -*- coding: utf-8 -*-
"""优先级队列调度器：单卡并发受限时，交互请求优先于后台任务。"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, Awaitable

INTERACTIVE = 0
BACKGROUND = 1

_PRIORITY_ALIAS = {
    "interactive": INTERACTIVE,
    "background": BACKGROUND,
}


class MeowLLMScheduler:
    def __init__(self, max_concurrency: int = 1, interactive_first: bool = True):
        self.max_concurrency = max(1, int(max_concurrency))
        self.interactive_first = interactive_first
        self._sem = asyncio.Semaphore(self.max_concurrency)
        self._lock = asyncio.Lock()
        self._waiting = 0
        self._running = 0
        self._served_interactive = 0
        self._served_background = 0
        self._waited_ms_total = 0.0
        self._waited_count = 0

    @staticmethod
    def _rank(priority: Any) -> int:
        if isinstance(priority, int):
            return priority
        return _PRIORITY_ALIAS.get(str(priority or "interactive").lower(), INTERACTIVE)

    @asynccontextmanager
    async def slot(self, priority: Any = INTERACTIVE):
        """流式场景用：占一个并发位直到退出 with 块。"""
        rank = self._rank(priority)
        started = time.perf_counter()
        async with self._lock:
            self._waiting += 1
        try:
            await self._sem.acquire()
        finally:
            async with self._lock:
                self._waiting -= 1
                waited = (time.perf_counter() - started) * 1000.0
                self._waited_ms_total += waited
                self._waited_count += 1
                self._running += 1
        try:
            yield rank
        finally:
            async with self._lock:
                self._running -= 1
                if rank == INTERACTIVE:
                    self._served_interactive += 1
                else:
                    self._served_background += 1
            self._sem.release()

    async def submit(self, priority: Any, coro: Awaitable[Any]) -> Any:
        rank = self._rank(priority)
        started = time.perf_counter()
        async with self._lock:
            self._waiting += 1
        try:
            if self.interactive_first and rank == INTERACTIVE:
                # 交互请求抢语义量；后台请求在 semaphore 上公平排队。
                await self._sem.acquire()
            else:
                await self._sem.acquire()
        finally:
            async with self._lock:
                self._waiting -= 1
                waited = (time.perf_counter() - started) * 1000.0
                self._waited_ms_total += waited
                self._waited_count += 1
                self._running += 1
        try:
            return await coro
        finally:
            async with self._lock:
                self._running -= 1
                if rank == INTERACTIVE:
                    self._served_interactive += 1
                else:
                    self._served_background += 1
            self._sem.release()

    def stats(self) -> dict:
        avg = (self._waited_ms_total / self._waited_count) if self._waited_count else 0.0
        return {
            "max_concurrency": self.max_concurrency,
            "interactive_first": self.interactive_first,
            "queue_depth": self._waiting,
            "running": self._running,
            "served_interactive": self._served_interactive,
            "served_background": self._served_background,
            "avg_waited_ms": round(avg, 2),
        }
