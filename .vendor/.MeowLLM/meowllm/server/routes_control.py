# -*- coding: utf-8 -*-
"""/meowllm/control/* —— 原生控制面（项目侧不用，运维与自测用）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from meowllm import (
    MeowLLM_CONTROL_PREFIX,
    MeowLLM_VERSION,
)
from meowllm.errors import MeowLLMContractError, MeowLLMError
from meowllm.server.state import MeowLLMServiceState

log = logging.getLogger("meowllm.routes.control")

router = APIRouter(prefix=MeowLLM_CONTROL_PREFIX, tags=["meowllm-control"])


def _state(request: Request) -> MeowLLMServiceState:
    state = getattr(request.app.state, "meowllm", None)
    if state is None:
        raise MeowLLMError("服务未初始化")
    return state


def _error(exc: MeowLLMError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status,
                        content={"meowllm": {"error": exc.to_dict()}})


@router.get("/health")
async def health(request: Request):
    state = _state(request)
    body = state.health()
    body["version"] = MeowLLM_VERSION
    return body


@router.get("/stats")
async def stats(request: Request):
    state = _state(request)
    body = state.metrics()
    body["version"] = MeowLLM_VERSION
    return body


@router.get("/gpu")
async def gpu(request: Request):
    """显卡/显存实时采样（实验台右侧面板用）。永不 500。"""
    from meowllm.server import gpu as gpu_mod

    return gpu_mod.sample()


@router.post("/reload")
async def reload_config(request: Request):
    """只重载配置，不重载权重。引擎相关变更需重启进程。"""
    state = _state(request)
    from meowllm.config import MeowLLMConfig

    try:
        fresh = MeowLLMConfig.load(state.cfg.source)
    except MeowLLMError as exc:
        return _error(exc)

    changed = []
    for key in ("gen.talk_max_tokens", "gen.temperature", "gen.top_p",
                "thinking.default_level", "thinking.budgets",
                "engine.dualstream.max_segments", "engine.dualstream.stop_after_no",
                "engine.dualstream.fast_prefill", "cache.prefix.enabled",
                "queue.max_concurrency"):
        if fresh.get(key) != state.cfg.get(key):
            changed.append(key)

    state.cfg = fresh
    return {"ok": True, "changed": changed,
            "note": "引擎与端口变更需要重启进程才生效"}


@router.post("/session/reset")
async def session_reset(request: Request):
    state = _state(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    session_id = str((body or {}).get("session_id") or "").strip()
    if not session_id:
        raise MeowLLMContractError("缺少 session_id")
    removed = state.session.reset(session_id)
    return {"ok": True, "session_id": session_id, "removed": removed}


@router.get("/version")
async def version():
    from meowllm import MeowLLM_API_VERSION

    return {"service": "MeowLLM", "version": MeowLLM_VERSION,
            "api": MeowLLM_API_VERSION}


# ------------------------------------------------------------------ δ-mem
@router.get("/dmem/status")
async def dmem_status(request: Request):
    state = _state(request)
    engine = state.engine
    fn = getattr(engine, "dmem_status", None)
    if fn is None:
        return {"enabled": False, "reason": "当前引擎不支持 δ-mem"}
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/dmem/write")
async def dmem_write(request: Request):
    """把一段文本写进某 owner（uid）的记忆状态。等价 mem0 的 add。"""
    state = _state(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body or {}
    owner = str(body.get("owner") or body.get("uid") or "").strip()
    text = str(body.get("text") or body.get("memory") or "")
    mode = str(body.get("mode") or "replace").strip().lower()
    if mode not in ("replace", "append"):
        raise MeowLLMContractError("mode 只能是 replace / append")
    fn = getattr(state.engine, "dmem_write", None)
    if fn is None:
        raise MeowLLMContractError("当前引擎不支持 δ-mem")
    try:
        stat = fn(owner, text, mode=mode)
    except MeowLLMError as exc:
        return _error(exc)
    return {"ok": True, **stat}


@router.post("/dmem/forget")
async def dmem_forget(request: Request):
    state = _state(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    owner = str((body or {}).get("owner") or "").strip()
    if not owner:
        raise MeowLLMContractError("缺少 owner")
    fn = getattr(state.engine, "dmem_forget", None)
    if fn is None:
        raise MeowLLMContractError("当前引擎不支持 δ-mem")
    return {"ok": True, **fn(owner)}


@router.post("/dmem/use")
async def dmem_use(request: Request):
    """手动切 owner（调试用；正常由生成请求的 meowllm.memory_owner 决定）。"""
    state = _state(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    owner = (body or {}).get("owner")
    registry = getattr(state.engine, "dmem_registry", None)
    if registry is None:
        raise MeowLLMContractError("当前引擎不支持 δ-mem")
    attached = registry.use(str(owner).strip() if owner else None)
    return {"ok": True, "owner": owner, "attached": attached,
            "registry": registry.stats()}
