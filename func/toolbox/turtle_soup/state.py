# -*- coding: utf-8 -*-
# func/toolbox/turtle_soup/state.py
# 海龟汤运行态：按会话隔离保存进行中的谜题、注入块与历史（仅存数据，不做业务）

import threading

from func.tools.singleton_mode import singleton


@singleton
class TBTurtleSoupState:
    """海龟汤运行态（单例，线程安全）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}  # session_key -> dict

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

    # ==================== 读写 ====================
    def start(self, key: str, puzzle: dict, game_block: str):
        with self._lock:
            self._sessions[key] = {
                "puzzle": puzzle or {},
                "game_block": game_block or "",
                "history": [],
            }

    def end(self, key: str):
        with self._lock:
            self._sessions.pop(key, None)

    def is_active(self, key: str) -> bool:
        with self._lock:
            return key in self._sessions

    def get(self, key: str) -> dict:
        with self._lock:
            return self._sessions.get(key)

    def get_puzzle(self, key: str) -> dict:
        s = self.get(key)
        return s.get("puzzle") if s else {}

    def get_game_block(self, key: str) -> str:
        s = self.get(key)
        return s.get("game_block", "") if s else ""

    def record_turn(self, key: str, role: str, content: str, limit: int = 20):
        with self._lock:
            s = self._sessions.get(key)
            if not s:
                return
            s["history"].append({"role": role, "content": content})
            if len(s["history"]) > limit:
                s["history"] = s["history"][-limit:]

    def get_history(self, key: str, limit: int = 6) -> list:
        s = self.get(key)
        if not s:
            return []
        return s["history"][-limit:]
