# -*- coding: utf-8 -*-
# func/toolbox/svg_painter/state.py
# 绘画模式运行态：按会话 key 隔离（live / qq_private / qq_group），每个 key 独立画布与进度
# 仅存数据，不做业务（业务在 core.py / agent.py）；key 规则与海龟汤一致

import threading
from datetime import datetime

from func.tools.singleton_mode import singleton


@singleton
class TBSvgPaintingState:
    """绘画会话态（单例，线程安全）。一个 key 一次只允许一个绘画会话，激活期全权接管输入"""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}  # key -> dict

    # ==================== 会话 key ====================
    @staticmethod
    def live_key() -> str:
        return "live"

    @staticmethod
    def private_key(user_id) -> str:
        return f"qq_private:{user_id}"

    @staticmethod
    def group_key(group_id) -> str:
        return f"qq_group:{group_id}"

    @staticmethod
    def channel_of(key: str) -> str:
        if key.startswith("qq_private:"):
            return "qq_private"
        if key.startswith("qq_group:"):
            return "qq_group"
        return "live"

    # ==================== 读写 ====================
    def start(self, key: str, board, username: str = "", topic: str = "",
              temp_dir: str = "", meta: dict = None):
        with self._lock:
            self._sessions[key] = {
                "channel": self.channel_of(key),
                "username": username or "",
                "board": board,          # 本会话独立画布（TBSvgBoardState 实例）
                "topic": topic or "",
                "temp_dir": temp_dir or "",   # 进行中的临时会话目录（.temp），完工后归档进 character
                "meta": meta or {},
                "inbox": [],             # 绘画期间用户插话队列（agent 线程轮询取走）
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    def end(self, key: str):
        with self._lock:
            self._sessions.pop(key, None)

    def is_active(self, key: str) -> bool:
        with self._lock:
            return key in self._sessions

    def get(self, key: str) -> dict:
        with self._lock:
            s = self._sessions.get(key)
            return dict(s) if s else None

    def get_ref(self, key: str):
        """返回会话内部 dict 引用（供 agent 写回 meta/temp_dir/topic，调用方注意锁由外层控制）"""
        with self._lock:
            return self._sessions.get(key)

    def get_board(self, key: str):
        s = self.get(key)
        return s.get("board") if s else None

    def update(self, key: str, **kw):
        with self._lock:
            s = self._sessions.get(key)
            if s:
                s.update(kw)

    def active_keys(self) -> list:
        with self._lock:
            return list(self._sessions.keys())
