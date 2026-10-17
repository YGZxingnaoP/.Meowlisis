# -*- coding: utf-8 -*-
"""引擎工厂 + 三道安全闸门。

闸门是硬约束的代码化：默认配置下本机只允许 stub，任何 >max_local_model_params_b
的模型在启动阶段就被拒绝，不可能被加载。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Callable

from meowllm.engine.base import MeowLLMEngineBase
from meowllm.errors import MeowLLMConfigError, MeowLLMEngineError, MeowLLMSafetyError

log = logging.getLogger("meowllm.engine.factory")

#: 文件名里的参数量，例如 Qwen3-0.6B-Q8_0.gguf -> 0.6
_PARAM_IN_NAME = re.compile(r"(?<![0-9.])(\d+(?:\.\d+)?)\s*B(?![A-Za-z0-9])")

#: 量化类型 -> 每权重比特数（用于按文件体积粗估参数量）
_BITS_PER_WEIGHT = (
    ("IQ1", 1.6), ("IQ2", 2.4), ("Q2", 3.0),
    ("IQ3", 3.4), ("Q3", 3.9),
    ("IQ4", 4.3), ("Q4", 4.5), ("MXFP4", 4.5),
    ("Q5", 5.5), ("Q6", 6.6), ("Q8", 8.5),
    ("BF16", 16.0), ("F16", 16.0), ("FP16", 16.0), ("F32", 32.0),
)

_REGISTRY: dict[str, Callable[[object], MeowLLMEngineBase]] = {}


def register(kind: str, builder: Callable[[object], MeowLLMEngineBase]) -> None:
    _REGISTRY[kind] = builder


def registered_kinds() -> list[str]:
    return sorted(_REGISTRY)


# ---------------------------------------------------------------- 参数量探测
def _bits_per_weight(name: str) -> float:
    upper = name.upper()
    for tag, bits in _BITS_PER_WEIGHT:
        if tag in upper:
            return bits
    return 4.5


def probe_params_b(path: str) -> float:
    """探测模型参数量（单位 B）。探测不到返回 inf —— 让闸门 fail-closed。"""
    if not path:
        return float("inf")
    try:
        if os.path.isdir(path):
            return _probe_hf_dir(path)
        if os.path.isfile(path):
            return _probe_file(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("参数量探测异常（按 inf 处理）: %s -> %s", path, exc)
        return float("inf")
    # 路径还不存在时，至少从文件名读一个数，让拒绝信息可读
    match = _PARAM_IN_NAME.search(os.path.basename(path))
    if match:
        try:
            value = float(match.group(1))
            log.warning("模型文件尚不存在，按文件名推断参数量: %s -> %.3fB", path, value)
            return value
        except ValueError:
            pass
    log.warning("参数量探测失败（路径不存在）: %s", path)
    return float("inf")


def _probe_hf_dir(path: str) -> float:
    cfg_path = os.path.join(path, "config.json")
    if not os.path.isfile(cfg_path):
        return float("inf")
    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    for key in ("num_parameters", "n_parameters", "total_params"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value) / 1e9
    text_cfg = raw.get("text_config") if isinstance(raw.get("text_config"), dict) else raw
    hidden = text_cfg.get("hidden_size")
    layers = text_cfg.get("num_hidden_layers")
    inter = text_cfg.get("intermediate_size")
    vocab = text_cfg.get("vocab_size")
    if all(isinstance(x, (int, float)) and x > 0 for x in (hidden, layers, inter, vocab)):
        # 粗略：每层 (attn 4h^2 + mlp 3*h*inter)
        per_layer = 4 * hidden * hidden + 3 * hidden * inter
        total = layers * per_layer + 2 * vocab * hidden
        return float(total) / 1e9
    return float("inf")


def _probe_file(path: str) -> float:
    name = os.path.basename(path)
    match = _PARAM_IN_NAME.search(name)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    size = os.path.getsize(path)
    if size <= 0:
        return float("inf")
    bits = _bits_per_weight(name)
    return (size * 8.0) / (bits * 1e9)


# ---------------------------------------------------------------- 闸门
def create(cfg) -> MeowLLMEngineBase:
    kind = str(cfg.get("engine.kind", "stub")).strip().lower()
    allow = cfg.get("safety.allow_engine", []) or []
    require_env = bool(cfg.get("safety.require_env_override", False))
    max_b = float(cfg.get("safety.max_local_model_params_b", 1.0))

    # 闸 1：白名单
    if kind not in allow:
        raise MeowLLMSafetyError(
            f"引擎 {kind!r} 不在白名单 {allow}，拒绝启动",
            detail={"engine": kind, "allow_engine": allow})

    if kind not in _REGISTRY:
        raise MeowLLMConfigError(
            f"未知引擎 {kind!r}，已注册: {registered_kinds()}",
            detail={"engine": kind, "registered": registered_kinds()})

    # 闸 2：非 stub 需显式放行
    if kind != "stub" and require_env:
        if os.environ.get("MEOWLLM_ALLOW_LOCAL_MODEL") != "1":
            raise MeowLLMSafetyError(
                "非 stub 引擎需要环境变量 MEOWLLM_ALLOW_LOCAL_MODEL=1 才允许启动",
                detail={"engine": kind})

    # 闸 3：参数量硬上限
    if kind != "stub":
        model_path = _model_path_of(cfg, kind)
        params_b = probe_params_b(model_path)
        if not (params_b <= max_b):
            raise MeowLLMSafetyError(
                f"拒绝加载：{params_b:.3f}B > 上限 {max_b:g}B（本机禁止运行超过上限的模型）",
                detail={"engine": kind, "model_path": model_path,
                        "params_b": None if params_b == float("inf") else round(params_b, 3),
                        "max_local_model_params_b": max_b})
        log.info("闸门通过：engine=%s params=%.3fB <= %.3fB", kind, params_b, max_b)

    builder = _REGISTRY[kind]
    engine = builder(cfg)
    engine._meowllm_params_b = _safe_params_b(kind, cfg)  # noqa: SLF001
    return engine


def _model_path_of(cfg, kind: str) -> str:
    if kind == "dualstream":
        raw = str(cfg.get("engine.dualstream.model_dir", "") or "")
        return cfg.resolve(raw)
    return ""


def _safe_params_b(kind: str, cfg) -> float:
    if kind == "stub":
        return 0.0
    try:
        return probe_params_b(_model_path_of(cfg, kind))
    except Exception:  # noqa: BLE001
        return float("inf")


def _register_builtins() -> None:
    from meowllm.engine.stub import MeowLLMEngineStub

    register("stub", MeowLLMEngineStub)

    def _dualstream(cfg):
        from meowllm.engine.dualstream import AsyncHFEngine
        return AsyncHFEngine(cfg)

    register("dualstream", _dualstream)


_register_builtins()
