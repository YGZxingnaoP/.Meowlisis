# -*- coding: utf-8 -*-
"""引擎抽象。上层（路由层）只认这里的接口，换引擎不动上层。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator

from meowllm.errors import MeowLLMEngineError

KIND_CONTENT = "content"
KIND_REASONING = "reasoning"
KIND_TOOL_CALL = "tool_call"
KIND_FINISH = "finish"
KIND_META = "meta"

#: 中文近似：1 token ≈ 1.6 字符。仅用于统计与缓存记账，不用于正确性判断。
CHARS_PER_TOKEN = 1.6


@dataclass
class MeowLLMGenParams:
    """一次生成请求的全部参数（已合并：请求级 > 配置级）。"""

    max_tokens: int = 512
    temperature: float = 0.8
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.05
    stop: list[str] = field(default_factory=list)
    seed: int | None = None

    thinking_level: str = "off"
    think_budget: int = 0

    tools: list[dict] | None = None
    tool_choice: Any = None

    session_id: str | None = None
    cache_key: str | None = None
    cache_enabled: bool = True
    pin_prefix: bool = True

    context_limit: int | None = None
    priority: str = "interactive"
    language: str | None = None

    #: 原始请求体里我们没消费的字段，留给引擎做透传
    raw: dict = field(default_factory=dict)

    @property
    def has_tools(self) -> bool:
        return bool(self.tools)


@dataclass
class MeowLLMGenEvent:
    """引擎吐出的最小事件单元。"""

    kind: str
    text: str = ""
    index: int = 0
    call_id: str | None = None
    name: str | None = None
    arguments_delta: str | None = None
    finish_reason: str | None = None
    meta: dict | None = None

    #: 该 token 来自哪条流。
    #: "reasoning"/"content" 这类通道由 kind 决定，本字段只用于区分同 kind 下的来源：
    #: dualstream 引擎里 reasoning 恒为 thinker、content 恒为 writer；
    #: 其它引擎可为空。上层不需要它也能正常工作，仅供观测。
    stream: str = ""


class MeowLLMEngineBase(ABC):
    """引擎基类。所有实现必须可被当作"可判活"的对象使用。"""

    kind: str = "abstract"

    def __init__(self, cfg):
        self.cfg = cfg
        self.log = logging.getLogger(f"meowllm.engine.{self.kind}")
        self._loaded = False
        self._last_error: str = ""

    # ---------- 判活 ----------
    @property
    def client(self) -> bool:
        """供上层 `if not engine.client` 判活，语义与项目 port 的 `llm.client` 对齐。"""
        return self._loaded

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def last_error(self) -> str:
        return self._last_error

    def require_loaded(self) -> None:
        if not self._loaded:
            raise MeowLLMEngineError(
                f"引擎 {self.kind} 未就绪", detail={"last_error": self._last_error})

    # ---------- 生命周期 ----------
    @abstractmethod
    def load(self) -> None:
        """加载模型 / 建立连接。失败抛 MeowLLMEngineError。"""

    def unload(self) -> None:
        self._loaded = False

    @abstractmethod
    def info(self) -> dict:
        """返回 {engine, model, params_b, quant, n_ctx, ...}"""

    # ---------- 推理 ----------
    @abstractmethod
    def count_tokens(self, messages: list[dict]) -> int:
        """近似 token 数（用于上下文裁剪与缓存记账）。"""

    @abstractmethod
    def generate(self, messages: list[dict],
                 params: MeowLLMGenParams) -> AsyncIterator[MeowLLMGenEvent]:
        """异步生成器。严禁把异常当成正常结束——必须抛出或产出 finish_reason='error'。"""

    # ---------- 缓存挂钩（默认为无能力） ----------
    def kv_slot_stats(self) -> dict:
        return {"supported": False}

    def cache_take(self, key: str) -> str | None:
        return None

    def cache_give(self, key: str, handle: str) -> None:
        return None

    # ---------- 工具 ----------
    @staticmethod
    def _truncate_history(messages: list[dict], budget_tokens: int) -> list[dict]:
        """超长时丢最早的历史，但保留头部 system 稳定段与最后一条消息。"""
        if budget_tokens <= 0:
            return messages
        heads: list[dict] = []
        idx = 0
        while idx < len(messages) and messages[idx].get("role") == "system":
            heads.append(messages[idx])
            idx += 1
        tail = messages[idx:]
        if not tail:
            return messages
        keep_last = tail[-1]
        middle = tail[:-1]

        def ratio(msg: dict) -> int:
            content = msg.get("content")
            if isinstance(content, str):
                return max(1, int(len(content) / CHARS_PER_TOKEN))
            return 1

        total = sum(ratio(m) for m in heads) + ratio(keep_last)
        kept: list[dict] = []
        for msg in reversed(middle):
            cost = ratio(msg)
            if total + cost > budget_tokens:
                break
            kept.append(msg)
            total += cost
        kept.reverse()
        return heads + kept + [keep_last]

    @staticmethod
    def _iter_text_chunks(text: str, size: int) -> Iterator[str]:
        step = max(1, int(size or 1))
        for i in range(0, len(text), step):
            yield text[i:i + step]
