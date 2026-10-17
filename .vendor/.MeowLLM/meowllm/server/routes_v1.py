# -*- coding: utf-8 -*-
"""/meowllm/v1/* —— OpenAI 兼容子集。"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from meowllm import MeowLLM_API_VERSION, MeowLLM_V1_PREFIX
from meowllm.errors import MeowLLMError, MeowLLMContractError
from meowllm.server.schema import (
    build_params,
    resolve_extras,
    validate_messages,
)
from meowllm.server.stream import (
    MeowLLMAccumulator,
    MeowLLMChunkWriter,
    sse_stream,
)
from meowllm.server.state import MeowLLMServiceState

log = logging.getLogger("meowllm.routes.v1")

router = APIRouter(prefix=MeowLLM_V1_PREFIX, tags=[MeowLLM_API_VERSION])


def _state(request: Request) -> MeowLLMServiceState:
    state = getattr(request.app.state, "meowllm", None)
    if state is None:
        raise MeowLLMError("服务未初始化")
    return state


def _error_response(exc: MeowLLMError) -> JSONResponse:
    body = {
        "error": {"type": "meowllm_error", **exc.to_dict()},
        "meowllm": {"error": exc.to_dict()},
    }
    return JSONResponse(status_code=exc.http_status, content=body)


@router.get("/models")
async def list_models(request: Request):
    state = _state(request)
    return {
        "object": "list",
        "data": [{
            "id": state.cfg.get("model.name"),
            "object": "model",
            "created": int(state.started_at),
            "owned_by": "meowllm",
            "meowllm": {"engine": state.engine.kind,
                        "loaded": state.engine.loaded},
        }],
    }


@router.post("/chat/completions")
async def chat_completions(request: Request):
    state = _state(request)
    started = time.perf_counter()

    try:
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise MeowLLMContractError(f"请求体不是合法 JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise MeowLLMContractError("请求体必须是 JSON 对象")

        messages = validate_messages(body)
        extras = resolve_extras(body)
        params = build_params(body, extras, state.cfg)
        stream_flag = bool(body.get("stream", False))

        prepared = state.prepare(messages, params)
        state.stats.requests += 1
        if stream_flag:
            state.stats.stream_requests += 1
        else:
            state.stats.nonstream_requests += 1

        model_name = state.cfg.get("model.name") or "meowllm-local"

        if stream_flag:
            return StreamingResponse(
                _streaming(state, prepared, params, model_name, started),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "X-MeowLLM-Engine": state.engine.kind,
                    "X-MeowLLM-Cache": prepared["cache_state"],
                },
            )

        return await _collect(state, prepared, params, model_name, started)

    except MeowLLMError as exc:
        state.stats.errors += 1
        if exc.http_status == 503:
            state.stats.timeouts += 1
        log.warning("请求失败: %s", exc.to_dict())
        return _error_response(exc)
    except Exception as exc:  # noqa: BLE001
        state.stats.errors += 1
        log.exception("未预期异常")
        return _error_response(MeowLLMError(f"内部错误: {exc}"))


async def _streaming(state: MeowLLMServiceState, prepared: dict,
                     params, model_name: str, started: float):
    from meowllm.engine.base import KIND_META, MeowLLMGenEvent

    writer = MeowLLMChunkWriter(model_name)
    first_byte_ms = {"value": 0.0}

    def _note_meta(meta: dict) -> None:
        timings = meta.get("timings") if isinstance(meta.get("timings"), dict) else meta
        state.prefix.note_engine_timings(timings)
        state.stats.note_prefill(float(meta.get("prefill_ms") or 0))
        state.stats.note_decode(float(meta.get("decode_tps") or 0))

    async def _events():
        try:
            async with state.scheduler.slot(params.priority):
                async for event in state.engine.generate(prepared["messages"], params):
                    if not first_byte_ms["value"] and event.kind in (
                            "content", "reasoning", "tool_call"):
                        first_byte_ms["value"] = (
                            time.perf_counter() - started) * 1000.0
                        state.stats.note_ttfb(first_byte_ms["value"])
                    yield event
        finally:
            state.finish_prefix(prepared, prepared.get("prefix_key", ""),
                                prepared.get("prefix_tokens", 0))

    async def _events_with_meta():
        async for event in _events():
            if event.kind == KIND_META:
                meta = dict(event.meta or {})
                meta.update(_common_meta(state, prepared, params,
                                         started, first_byte_ms))
                event = MeowLLMGenEvent(kind=KIND_META, meta=meta)
            yield event

    async for chunk in sse_stream(_events_with_meta(), writer, on_meta=_note_meta):
        yield chunk


def _common_meta(state, prepared, params, started, first_byte_ms) -> dict:
    return {
        "cache": prepared["cache_state"],
        "prefix_tokens": prepared["prefix_tokens"],
        "truncated_history": prepared["truncated"],
        "thinking_level": params.thinking_level,
        "think_budget": params.think_budget,
        "session_id": params.session_id,
        "ttfb_ms": round(first_byte_ms.get("value") or 0.0, 3),
        "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "queue": state.scheduler.stats(),
    }


async def _collect(state: MeowLLMServiceState, prepared: dict,
                   params, model_name: str, started: float):
    acc = MeowLLMAccumulator(model_name)
    first_byte_ms = {"value": 0.0}

    async with state.scheduler.slot(params.priority):
        async for event in state.engine.generate(prepared["messages"], params):
            if not first_byte_ms["value"] and event.kind in (
                    "content", "reasoning", "tool_call"):
                first_byte_ms["value"] = (time.perf_counter() - started) * 1000.0
                state.stats.note_ttfb(first_byte_ms["value"])
            acc.feed(event)

    state.finish_prefix(prepared, prepared.get("prefix_key", ""),
                        prepared.get("prefix_tokens", 0))

    timings = acc.meta.get("timings") if isinstance(acc.meta.get("timings"), dict) else acc.meta
    state.prefix.note_engine_timings(timings)
    state.stats.note_prefill(float(acc.meta.get("prefill_ms") or 0))
    state.stats.note_decode(float(acc.meta.get("decode_tps") or 0))

    if not acc.content and not acc.tool_calls_payload():
        state.stats.empty_content += 1
    if acc.tool_calls_payload():
        state.stats.tool_responses += 1

    meta = dict(acc.meta)
    meta.update(_common_meta(state, prepared, params, started, first_byte_ms))
    acc.meta = meta

    payload = acc.completion()
    return JSONResponse(content=payload, headers={
        "X-MeowLLM-Engine": state.engine.kind,
        "X-MeowLLM-Cache": prepared["cache_state"],
    })
