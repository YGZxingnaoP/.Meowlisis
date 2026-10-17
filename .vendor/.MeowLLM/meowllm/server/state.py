# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
import os
import time
from collections import deque

from meowllm.cache.prefix import MeowLLMPrefixCache
from meowllm.cache.session import MeowLLMSessionCache
from meowllm.engine.base import MeowLLMEngineBase, MeowLLMGenParams
from meowllm.scheduler import MeowLLMScheduler

log = logging.getLogger("meowllm.state")

_SAMPLE_WINDOW = 512


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


class MeowLLMStats:
    def __init__(self):
        self.requests = 0
        self.stream_requests = 0
        self.nonstream_requests = 0
        self.errors = 0
        self.timeouts = 0
        self.empty_content = 0
        self.tool_requests = 0
        self.tool_responses = 0
        self.truncated_requests = 0
        self._ttfb: deque[float] = deque(maxlen=_SAMPLE_WINDOW)
        self._decode: deque[float] = deque(maxlen=_SAMPLE_WINDOW)
        self._prefill: deque[float] = deque(maxlen=_SAMPLE_WINDOW)

    def note_ttfb(self, ms: float) -> None:
        if ms and ms > 0:
            self._ttfb.append(float(ms))

    def note_prefill(self, ms: float) -> None:
        if ms and ms > 0:
            self._prefill.append(float(ms))

    def note_decode(self, tps: float) -> None:
        if tps and tps > 0:
            self._decode.append(float(tps))

    def snapshot(self) -> dict:
        return {
            "requests": self.requests,
            "stream_requests": self.stream_requests,
            "nonstream_requests": self.nonstream_requests,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "empty_content": self.empty_content,
            "empty_content_rate": (round(self.empty_content / self.requests, 4)
                                   if self.requests else 0.0),
            "tool_requests": self.tool_requests,
            "tool_responses": self.tool_responses,
            "truncated_requests": self.truncated_requests,
            "ttfb_p50": _percentile(list(self._ttfb), 50),
            "ttfb_p95": _percentile(list(self._ttfb), 95),
            "prefill_ms_p50": _percentile(list(self._prefill), 50),
            "decode_tps_p50": _percentile(list(self._decode), 50),
            "samples": len(self._ttfb),
        }


class MeowLLMServiceState:
    def __init__(self, cfg, engine: MeowLLMEngineBase):
        self.cfg = cfg
        self.engine = engine
        self.started_at = time.time()
        self.stats = MeowLLMStats()

        prefix_cfg = cfg.section("cache").get("prefix") or {}
        self.prefix = MeowLLMPrefixCache(
            slots=int(prefix_cfg.get("slots", 4)),
            min_prefix_tokens=int(prefix_cfg.get("min_prefix_tokens", 256)),
            volatile_markers=list(prefix_cfg.get("volatile_markers") or []),
            enabled=bool(prefix_cfg.get("enabled", True)),
        )
        session_cfg = cfg.section("cache").get("session") or {}
        self.session = MeowLLMSessionCache(
            max_sessions=int(session_cfg.get("max_sessions", 8)),
            ttl_seconds=int(session_cfg.get("ttl_seconds", 3600)),
            enabled=bool(session_cfg.get("enabled", True)),
        )
        queue_cfg = cfg.section("queue")
        self.scheduler = MeowLLMScheduler(
            max_concurrency=int(queue_cfg.get("max_concurrency", 1)),
            interactive_first=bool(queue_cfg.get("interactive_first", True)),
        )

        self._failed_dirs = cfg.ensure_dirs()
        if self._failed_dirs:
            log.warning("以下目录无法创建（运行态可能写不进去）：%s", self._failed_dirs)

    def prepare(self, messages: list[dict], params: MeowLLMGenParams) -> dict:
        engine = self.engine

        context_limit = int(params.context_limit or self.cfg.get("context.n_ctx", 8192))
        cap = int(self.cfg.get("context.max_prompt_tokens", 0) or 0)
        budget = max(1024, context_limit - int(params.max_tokens))
        if cap:
            budget = min(budget, cap)
        trimmed = engine._truncate_history(messages, budget)
        trimmed = self._fit_tokens(trimmed, budget)
        truncated = max(0, len(messages) - len(trimmed))

        key, prefix_tokens = self.prefix.key_of(trimmed)
        entry = self.prefix.lookup(key) if key else None
        cache_state = "hit" if entry else ("bypass" if not key else "miss")

        session_entry = None
        if params.session_id:
            session_entry = self.session.touch(params.session_id, prefix_tokens)

        if truncated:
            self.stats.truncated_requests += 1
        if params.tools:
            self.stats.tool_requests += 1

        return {
            "messages": trimmed,
            "truncated": truncated,
            "prefix_key": key,
            "prefix_tokens": prefix_tokens,
            "cache_state": cache_state,
            "session": session_entry,
        }

    def _fit_tokens(self, messages: list[dict], limit: int) -> list[dict]:
        counter = getattr(self.engine, "count_tokens", None)
        if counter is None or not messages:
            return messages
        try:
            if counter(messages) <= limit:
                return messages
        except Exception:
            return messages
        rows = list(messages)
        head: list[dict] = []
        if str(rows[0].get("role") or "") == "system":
            head = [rows[0]]
            rows = rows[1:]
        if not rows:
            return head
        tail = rows[-1:]
        middle = rows[:-1]
        while middle:
            try:
                if counter(head + middle + tail) <= limit:
                    break
            except Exception:
                break
            step = max(1, len(middle) // 10)
            middle = middle[step:]
        return head + middle + tail

    def finish_prefix(self, prepared: dict, key: str, tokens: int) -> None:
        if key:
            engine_slot = None
            if prepared.get("session"):
                engine_slot = prepared["session"].get("engine_slot")
            self.prefix.give(key, tokens, engine_slot)

    def health(self) -> dict:
        try:
            info = self.engine.info()
        except Exception as exc:
            info = {"error": str(exc)}
        return {
            "ready": bool(self.engine.loaded),
            "service": "MeowLLM",
            "uptime_s": round(time.time() - self.started_at, 1),
            "config": self.cfg.dump_safe(),
            "engine": info,
            "paths": {
                "state_dir": self.cfg.state_dir,
                "log_dir": self.cfg.log_dir,
                "state_dir_writable": not _in(self.cfg.state_dir,
                                              self._failed_dirs),
                "log_dir_writable": not _in(self.cfg.log_dir, self._failed_dirs),
            },
        }

    def metrics(self) -> dict:
        return {
            "cache": {"prefix": self.prefix.stats(), "session": self.session.stats()},
            "perf": self.stats.snapshot(),
            "queue": self.scheduler.stats(),
            "engine": {"kind": self.engine.kind,
                       "loaded": self.engine.loaded,
                       "kv": self.engine.kv_slot_stats()},
        }


def _in(path: str, failed: list[str]) -> bool:
    target = os.path.normcase(os.path.abspath(path or ""))
    return any(os.path.normcase(os.path.abspath(f or "")) == target for f in failed)
