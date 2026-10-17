# -*- coding: utf-8 -*-
"""会话级缓存记账：per-session（= per-meowid）token 累计 + TTL/LRU 淘汰。

B2 阶段只记账；真正的 KV 落盘由 llama-server 的 --slot-save-path 负责，
后续要把 session_id 映射到 id_slot 时，把 slot 句柄存在这里即可。
"""

from __future__ import annotations

import time


class MeowLLMSessionCache:
    def __init__(self, max_sessions: int = 8, ttl_seconds: int = 3600,
                 enabled: bool = True):
        self.enabled = bool(enabled)
        self.max_sessions = max(1, int(max_sessions))
        self.ttl_seconds = max(0, int(ttl_seconds))
        self._entries: dict[str, dict] = {}
        self._evicted = 0
        self._resets = 0

    def get(self, session_id: str | None) -> dict | None:
        if not self.enabled or not session_id:
            return None
        entry = self._entries.get(session_id)
        if entry is None:
            return None
        if self._expired(entry):
            self._entries.pop(session_id, None)
            self._evicted += 1
            return None
        return entry

    def touch(self, session_id: str | None, tokens_delta: int = 0) -> dict | None:
        if not self.enabled or not session_id:
            return None
        now = time.time()
        entry = self._entries.get(session_id)
        if entry is None or self._expired(entry):
            entry = {
                "session_id": session_id,
                "tokens": 0,
                "turns": 0,
                "engine_slot": None,
                "created": now,
            }
            self._entries[session_id] = entry
        entry["tokens"] = int(entry.get("tokens", 0)) + max(0, int(tokens_delta))
        entry["turns"] = int(entry.get("turns", 0)) + 1
        entry["last_seen"] = now
        self._enforce_capacity()
        return entry

    def bind_slot(self, session_id: str | None, slot: str | None) -> None:
        if not self.enabled or not session_id:
            return
        entry = self._entries.get(session_id)
        if entry is not None:
            entry["engine_slot"] = slot

    def reset(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        self._resets += 1
        return self._entries.pop(session_id, None) is not None

    def evict_expired(self) -> int:
        if not self.enabled:
            return 0
        dead = [sid for sid, e in self._entries.items() if self._expired(e)]
        for sid in dead:
            self._entries.pop(sid, None)
        self._evicted += len(dead)
        return len(dead)

    def stats(self) -> dict:
        total_tokens = sum(int(e.get("tokens", 0)) for e in self._entries.values())
        total_turns = sum(int(e.get("turns", 0)) for e in self._entries.values())
        return {
            "enabled": self.enabled,
            "sessions": len(self._entries),
            "max_sessions": self.max_sessions,
            "ttl_seconds": self.ttl_seconds,
            "total_tokens": total_tokens,
            "total_turns": total_turns,
            "evicted": self._evicted,
            "resets": self._resets,
            "session_ids": sorted(self._entries)[:16],
        }

    # ---------------- 内部 ----------------
    def _expired(self, entry: dict) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return (time.time() - float(entry.get("last_seen", entry.get("created", 0)))
                ) > self.ttl_seconds

    def _enforce_capacity(self) -> None:
        while len(self._entries) > self.max_sessions:
            oldest = min(self._entries.values(),
                         key=lambda e: e.get("last_seen", e.get("created", 0)))
            self._entries.pop(oldest["session_id"], None)
            self._evicted += 1
