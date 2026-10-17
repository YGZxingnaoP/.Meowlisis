# -*- coding: utf-8 -*-
"""前缀缓存记账。

重要说明
--------
这里的 key 是**记账用的 key**，不是真正送给引擎的 KV 句柄。真正的 kv 是否命中由
引擎自己决定（llama.cpp 用 cache_prompt 与 slot 文件）。本类负责：

  1. 从 messages 里切出"稳定前缀"（用于判断两次请求是否共享同一段头部）
  2. 记账命中次数、缓存 token 数
  3. 把引擎回报的真实 timings（prompt_n / cache_n）汇总进统计

切分规则
--------
* 只取最后一条 user 消息**之前**的所有消息（最后一条是本轮输入，必然不同）
* 若 system 内容里出现易变标记（默认 "# 现在是" / "我心里装着的" / "# 当前情绪"），
  则在第一个标记处截断 —— 截出来的仍然是原文的真实前缀，所以是真前缀。

易变标记可配：cache.prefix.volatile_markers
"""

from __future__ import annotations

import hashlib
import json
import time

from meowllm.engine.base import CHARS_PER_TOKEN


class MeowLLMPrefixCache:
    def __init__(self, slots: int = 4, min_prefix_tokens: int = 256,
                 volatile_markers: list[str] | None = None, enabled: bool = True):
        self.enabled = bool(enabled)
        self.slots = max(1, int(slots))
        self.min_prefix_tokens = max(0, int(min_prefix_tokens))
        self.volatile_markers = [m for m in (volatile_markers or []) if m]
        self._entries: dict[str, dict] = {}
        self._hits = 0
        self._misses = 0
        self._bypass = 0
        self._cached_tokens = 0
        self._engine_prompt_n = 0
        self._engine_cache_n = 0

    # ---------------- 切分 ----------------
    def _truncate_at_marker(self, text: str) -> str:
        cut = len(text)
        for marker in self.volatile_markers:
            pos = text.find(marker)
            if 0 <= pos < cut:
                cut = pos
        return text[:cut]

    def stable_prefix(self, messages: list[dict]) -> list[dict]:
        if not messages:
            return []
        cut = len(messages) - 1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                cut = i
                break
        head = messages[:cut]
        if not head:
            return []
        out: list[dict] = []
        for i, msg in enumerate(head):
            content = msg.get("content")
            if i == 0 and isinstance(content, str) and self.volatile_markers:
                content = self._truncate_at_marker(content)
            out.append({"role": msg.get("role"), "content": content})
        return out

    # ---------------- key ----------------
    def key_of(self, messages: list[dict]) -> tuple[str, int]:
        """返回 (key, 估算 token 数)。禁用或太短时返回 ("", 0)。"""
        if not self.enabled:
            self._bypass += 1
            return "", 0
        prefix = self.stable_prefix(messages)
        if not prefix:
            self._bypass += 1
            return "", 0
        blob = json.dumps(prefix, ensure_ascii=False, sort_keys=True)
        tokens = max(1, int(round(len(blob) / CHARS_PER_TOKEN)))
        if tokens < self.min_prefix_tokens:
            self._bypass += 1
            return "", tokens
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16], tokens

    # ---------------- 记账 ----------------
    def lookup(self, key: str) -> dict | None:
        """仅记账：命中返回条目（含引擎给的 slot 句柄，若有）。"""
        if not key:
            return None
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        self._hits += 1
        self._cached_tokens += int(entry.get("tokens", 0))
        entry["hits"] = int(entry.get("hits", 0)) + 1
        entry["last_seen"] = time.time()
        return entry

    def give(self, key: str, tokens: int, engine_slot: str | None = None) -> None:
        if not key:
            return
        self._entries[key] = {
            "key": key,
            "tokens": int(tokens),
            "engine_slot": engine_slot,
            "hits": 0,
            "created": time.time(),
            "last_seen": time.time(),
        }
        while len(self._entries) > self.slots:
            oldest = min(self._entries.values(), key=lambda e: e.get("last_seen", 0))
            self._entries.pop(oldest["key"], None)

    def note_engine_timings(self, timings: dict | None) -> None:
        """把引擎回报的真实 prompt_n / cache_n 记进统计。"""
        if not isinstance(timings, dict):
            return
        try:
            if timings.get("prompt_n") is not None:
                self._engine_prompt_n += int(timings["prompt_n"])
            if timings.get("cache_n") is not None:
                self._engine_cache_n += int(timings["cache_n"])
        except (TypeError, ValueError):
            pass

    def stats(self) -> dict:
        total = self._hits + self._misses
        engine_total = self._engine_prompt_n + self._engine_cache_n
        return {
            "enabled": self.enabled,
            "slots": self.slots,
            "min_prefix_tokens": self.min_prefix_tokens,
            "entries": len(self._entries),
            "hits": self._hits,
            "misses": self._misses,
            "bypass": self._bypass,
            "hit_rate": round(self._hits / total, 4) if total else 0.0,
            "cached_tokens": self._cached_tokens,
            "engine_prompt_n": self._engine_prompt_n,
            "engine_cache_n": self._engine_cache_n,
            "engine_cache_hit_rate": (round(self._engine_cache_n / engine_total, 4)
                                      if engine_total else 0.0),
        }
