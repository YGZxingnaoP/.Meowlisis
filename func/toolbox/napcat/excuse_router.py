# -*- coding: utf-8 -*-
# func/toolbox/napcat/excuse_router.py
# NapCat QQ excuse 等待路由：绑定用户，等待该用户下一条文本回复
# 供 weather/news 的 napcat_plugin 复用；napcat_core 收到消息时优先路由消费。

import queue
import threading

from func.tools.singleton_mode import singleton


@singleton
class TBNapcatExcuseRouter:
    """QQ excuse 等待路由（绑定用户，禁止串线）

    - 私聊 key = private:{user_id}
    - 群聊 key = group:{group_id}:{user_id}
    napcat_core 收到消息时，先构造 key 调 route()，命中则消费该消息并返回 True，
    表示「消息被 excuse 流程接管」，不再走正常 LLM 回复链路。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._waiters = {}  # key -> queue.Queue

    @staticmethod
    def private_key(user_id) -> str:
        return f"private:{user_id}"

    @staticmethod
    def group_key(group_id, user_id) -> str:
        return f"group:{group_id}:{user_id}"

    def register(self, key: str) -> queue.Queue:
        """注册等待队列（绑定用户），返回用于阻塞等待的 Queue"""
        q = queue.Queue()
        with self._lock:
            self._waiters[key] = q
        return q

    def unregister(self, key: str):
        with self._lock:
            self._waiters.pop(key, None)

    def route(self, key: str, text: str) -> bool:
        """收到 QQ 消息时路由：命中等待队列则 put 文本并返回 True（已被接管）"""
        with self._lock:
            q = self._waiters.get(key)
        if q:
            q.put(text)
            return True
        return False

    def is_waiting(self, key: str) -> bool:
        with self._lock:
            return key in self._waiters
