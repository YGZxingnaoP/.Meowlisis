# -*- coding: utf-8 -*-
"""OpenAI 流式分片封装 + 非流式聚合。

硬约束（来自项目真实消费点 `func/pipeline/llm_toolbox.py::ToolCallAccumulator`）
-----------------------------------------------------------------------------
* 同一个 ``id`` 贯穿整个流
* ``object`` 恒为 ``chat.completion.chunk``，``created`` 恒定
* 第一片 delta 带 ``role: assistant``
* tool_call 首片带 ``id`` + ``type`` + ``function.name``，后续片只带
  ``index`` + ``arguments`` 增量
* 末片 ``finish_reason`` 非空，之后才发 ``[DONE]``
"""

from __future__ import annotations

import json
import time
import uuid
from typing import AsyncIterator

from meowllm.engine.base import (
    KIND_CONTENT,
    KIND_FINISH,
    KIND_META,
    KIND_REASONING,
    KIND_TOOL_CALL,
    MeowLLMGenEvent,
)

SSE_DONE = b"data: [DONE]\n\n"
_OBJECT_CHUNK = "chat.completion.chunk"
_OBJECT_COMPLETION = "chat.completion"


def new_response_id() -> str:
    return "chatcmpl-meowllm-" + uuid.uuid4().hex[:20]


def to_sse(obj: dict) -> bytes:
    return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")


class MeowLLMChunkWriter:
    def __init__(self, model: str, response_id: str | None = None,
                 created: int | None = None):
        self.model = model
        self.id = response_id or new_response_id()
        self.created = created if created is not None else int(time.time())
        self._role_sent = False
        self._meta: dict = {}

    def _wrap(self, delta: dict, finish_reason: str | None = None) -> dict:
        return {
            "id": self.id,
            "object": _OBJECT_CHUNK,
            "created": self.created,
            "model": self.model,
            "choices": [{"index": 0, "delta": delta,
                         "logprobs": None, "finish_reason": finish_reason}],
        }

    def role(self) -> dict:
        self._role_sent = True
        return self._wrap({"role": "assistant", "content": ""})

    def content(self, text: str) -> dict:
        delta = {"content": text}
        if not self._role_sent:
            delta["role"] = "assistant"
            self._role_sent = True
        return self._wrap(delta)

    def reasoning(self, text: str) -> dict:
        delta = {"reasoning_content": text}
        if not self._role_sent:
            delta["role"] = "assistant"
            self._role_sent = True
        return self._wrap(delta)

    def tool_call(self, index: int, call_id: str | None = None,
                  name: str | None = None,
                  arguments_delta: str | None = None) -> dict:
        function: dict = {}
        if name:
            function["name"] = name
        if arguments_delta is not None:
            function["arguments"] = arguments_delta
        call: dict = {"index": int(index), "function": function}
        if call_id:
            call["id"] = call_id
            call["type"] = "function"
        delta = {"tool_calls": [call]}
        if not self._role_sent:
            delta["role"] = "assistant"
            self._role_sent = True
        return self._wrap(delta)

    def finish(self, reason: str) -> dict:
        return self._wrap({}, finish_reason=reason)

    def meta(self, meta: dict) -> dict:
        self._meta = dict(meta or {})
        return {
            "id": self.id,
            "object": _OBJECT_CHUNK,
            "created": self.created,
            "model": self.model,
            "choices": [],
            "meowllm": self._meta,
        }


def event_to_chunk(writer: MeowLLMChunkWriter, event: MeowLLMGenEvent) -> dict | None:
    if event.kind == KIND_CONTENT:
        return writer.content(event.text)
    if event.kind == KIND_REASONING:
        return writer.reasoning(event.text)
    if event.kind == KIND_TOOL_CALL:
        return writer.tool_call(event.index, event.call_id, event.name,
                                event.arguments_delta)
    if event.kind == KIND_FINISH:
        return writer.finish(event.finish_reason or "stop")
    if event.kind == KIND_META:
        return writer.meta(event.meta or {})
    return None


class MeowLLMAccumulator:
    """把事件流聚合成一个完整的非流式响应。"""

    def __init__(self, model: str):
        self.model = model
        self.id = new_response_id()
        self.created = int(time.time())
        self.content_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self.tool_calls: dict[int, dict] = {}
        self.finish_reason = "stop"
        self.meta: dict = {}

    def feed(self, event: MeowLLMGenEvent) -> None:
        if event.kind == KIND_CONTENT:
            self.content_parts.append(event.text)
        elif event.kind == KIND_REASONING:
            self.reasoning_parts.append(event.text)
        elif event.kind == KIND_TOOL_CALL:
            entry = self.tool_calls.setdefault(
                int(event.index), {"id": "", "name": "", "arguments": ""})
            if event.call_id:
                entry["id"] = event.call_id
            if event.name:
                entry["name"] = event.name
            if event.arguments_delta:
                entry["arguments"] += event.arguments_delta
        elif event.kind == KIND_FINISH:
            self.finish_reason = event.finish_reason or "stop"
            self.meta.update(event.meta or {})
        elif event.kind == KIND_META:
            self.meta.update(event.meta or {})

    @property
    def content(self) -> str:
        return "".join(self.content_parts)

    @property
    def reasoning(self) -> str:
        return "".join(self.reasoning_parts)

    def tool_calls_payload(self) -> list[dict]:
        out: list[dict] = []
        for index in sorted(self.tool_calls):
            call = self.tool_calls[index]
            if not call["name"]:
                continue
            out.append({
                "id": call["id"] or f"call_{index}",
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"] or "{}",
                },
            })
        return out

    def completion(self) -> dict:
        tool_calls = self.tool_calls_payload()
        message: dict = {"role": "assistant", "content": self.content}
        if self.reasoning:
            message["reasoning_content"] = self.reasoning
        if tool_calls:
            message["tool_calls"] = tool_calls
        finish = "tool_calls" if tool_calls else self.finish_reason
        prompt_tokens = int(self.meta.get("prompt_tokens")
                            or self.meta.get("prompt_n") or 0)
        completion_tokens = int(self.meta.get("completion_tokens")
                                or self.meta.get("predicted_n") or 0)
        return {
            "id": self.id,
            "object": _OBJECT_COMPLETION,
            "created": self.created,
            "model": self.model,
            "choices": [{
                "index": 0,
                "message": message,
                "logprobs": None,
                "finish_reason": finish,
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "meowllm": self.meta,
        }


async def sse_stream(events: AsyncIterator[MeowLLMGenEvent],
                     writer: MeowLLMChunkWriter,
                     on_meta=None) -> AsyncIterator[bytes]:
    """事件流 -> SSE 字节流。"""
    yielded_any = False
    try:
        yield to_sse(writer.role())
        async for event in events:
            if event.kind == KIND_META:
                if on_meta is not None:
                    on_meta(event.meta or {})
                continue
            chunk = event_to_chunk(writer, event)
            if chunk is None:
                continue
            yielded_any = True
            yield to_sse(chunk)
    except Exception as exc:  # noqa: BLE001
        # 已开始输出时无法改状态码，只能补一个错误块再结束
        yield to_sse({
            "id": writer.id,
            "object": _OBJECT_CHUNK,
            "created": writer.created,
            "model": writer.model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
            "meowllm": {"error": {"code": getattr(exc, "code", "meowllm.error"),
                                  "message": str(exc)}},
        })
        if not yielded_any:
            yield to_sse(writer.finish("error"))
        yield SSE_DONE
        return
    yield SSE_DONE
