# -*- coding: utf-8 -*-
"""请求解析与参数归一。

三个来源合并成 :class:`MeowLLMGenParams`，优先级：

    请求体顶层 ``meowllm`` 对象  >  OpenAI 标准字段  >  config.yml 默认值

兼容映射（让项目现有 port 一行不改就能用）
------------------------------------------
openai SDK 的 ``extra_body={...}`` 会把内容平铺进请求体顶层，所以项目现有的
port 实际发出来的是顶层 ``thinking`` / ``parameters`` / ``reasoning_effort``。
这里把它们统一映射成 ``thinking_level``：

    thinking.type == "disabled"                 -> off
    thinking.type == "enabled"                  -> medium
    parameters.enable_thinking == false         -> off
    reasoning_effort: none/low/medium/high      -> 对应档位（none -> off）

未知字段一律忽略并记 debug 日志，不报错。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from meowllm.engine.base import MeowLLMGenParams
from meowllm.errors import MeowLLMContractError

_THINKING_LEVELS = ("off", "low", "medium", "high")
_PRIORITIES = ("interactive", "background")


@dataclass
class MeowLLMExtras:
    """`meowllm` 命名空间 + 旧字段映射后的结果。"""

    thinking_level: str | None = None
    think_budget: int | None = None
    session_id: str | None = None
    context_limit: int | None = None
    max_tokens: int | None = None
    cache_enabled: bool | None = None
    pin_prefix: bool | None = None
    priority: str | None = None
    language: str | None = None
    #: δ-mem 记忆归属（uid）
    memory_owner: str | None = None
    #: 生成前临时写入状态的文本列表
    memory_write: list[str] = field(default_factory=list)
    origin: str = "default"
    unknown: list[str] = field(default_factory=list)


def _as_int(value: Any, name: str, *, minimum: int | None = None,
            maximum: int | None = None) -> int | None:
    if value is None:
        return None
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise MeowLLMContractError(f"{name} 必须是整数: {value!r}") from exc
    if minimum is not None and out < minimum:
        raise MeowLLMContractError(f"{name} 必须 >= {minimum}: {out}")
    if maximum is not None and out > maximum:
        raise MeowLLMContractError(f"{name} 必须 <= {maximum}: {out}")
    return out


def _as_float(value: Any, name: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise MeowLLMContractError(f"{name} 必须是数字: {value!r}") from exc


def _as_text_list(value: Any, name: str) -> list[str]:
    """字符串列表（也接受单个字符串）。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    raise MeowLLMContractError(f"{name} 必须是字符串或字符串数组: {value!r}")


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "enabled"):
        return True
    if text in ("0", "false", "no", "off", "disabled"):
        return False
    return None


def normalize_level(value: Any) -> str | None:
    """把各种写法收敛成 off/low/medium/high。"""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in _THINKING_LEVELS:
        return text
    if text in ("none", "false", "disabled", "0", "off"):
        return "off"
    if text in ("true", "enabled", "on", "auto", "1"):
        return "medium"
    if text in ("minimal", "lowest"):
        return "low"
    if text in ("max", "highest", "xhigh"):
        return "high"
    return None


def parse_meowllm_block(body: dict) -> MeowLLMExtras:
    """解析顶层的 meowllm 对象（即 extra_body.meowllm）。"""
    block = body.get("meowllm")
    if block is None:
        return MeowLLMExtras()
    if not isinstance(block, dict):
        raise MeowLLMContractError("meowllm 必须是对象")

    known = {
        "thinking_level", "think_budget", "session_id", "context_limit",
        "max_tokens", "cache", "priority", "language",
        "memory_owner", "memory_write",
    }
    unknown = [k for k in block if k not in known]

    cache = block.get("cache")
    cache_enabled = None
    pin_prefix = None
    if isinstance(cache, dict):
        cache_enabled = _as_bool(cache.get("enabled"))
        pin_prefix = _as_bool(cache.get("pin_prefix"))
        unknown += [f"cache.{k}" for k in cache
                    if k not in ("enabled", "pin_prefix")]

    priority = block.get("priority")
    if priority is not None:
        priority = str(priority).strip().lower()
        if priority not in _PRIORITIES:
            raise MeowLLMContractError(
                f"meowllm.priority 只能是 {_PRIORITIES}: {priority!r}")

    return MeowLLMExtras(
        thinking_level=normalize_level(block.get("thinking_level")),
        think_budget=_as_int(block.get("think_budget"), "meowllm.think_budget",
                             minimum=0, maximum=32768),
        session_id=(str(block["session_id"]).strip()
                    if block.get("session_id") else None),
        context_limit=_as_int(block.get("context_limit"), "meowllm.context_limit",
                              minimum=1024, maximum=1048576),
        max_tokens=_as_int(block.get("max_tokens"), "meowllm.max_tokens",
                           minimum=1, maximum=131072),
        cache_enabled=cache_enabled,
        pin_prefix=pin_prefix,
        priority=priority,
        language=(str(block["language"]).strip() if block.get("language") else None),
        memory_owner=(str(block["memory_owner"]).strip()
                      if block.get("memory_owner") else None),
        memory_write=_as_text_list(block.get("memory_write"), "meowllm.memory_write"),
        origin="meowllm",
        unknown=unknown,
    )


def parse_legacy(body: dict) -> MeowLLMExtras:
    """兼容项目现有 port 发出的 thinking / parameters / reasoning_effort。"""
    extras = MeowLLMExtras(origin="legacy")
    used = False

    thinking = body.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") is not None:
        extras.thinking_level = normalize_level(thinking.get("type"))
        used = used or extras.thinking_level is not None

    params = body.get("parameters")
    if isinstance(params, dict) and "enable_thinking" in params:
        enabled = _as_bool(params.get("enable_thinking"))
        if enabled is not None:
            extras.thinking_level = "medium" if enabled else "off"
            used = True

    if body.get("reasoning_effort") is not None:
        level = normalize_level(body.get("reasoning_effort"))
        if level is not None:
            extras.thinking_level = level
            used = True

    if not used:
        return MeowLLMExtras(origin="default")
    return extras


def resolve_extras(body: dict) -> MeowLLMExtras:
    """meowllm 块优先；缺的字段由 legacy 补齐。"""
    own = parse_meowllm_block(body)
    legacy = parse_legacy(body)
    merged = MeowLLMExtras(
        thinking_level=own.thinking_level if own.thinking_level is not None
        else legacy.thinking_level,
        think_budget=own.think_budget,
        session_id=own.session_id,
        context_limit=own.context_limit,
        max_tokens=own.max_tokens,
        cache_enabled=own.cache_enabled,
        pin_prefix=own.pin_prefix,
        priority=own.priority,
        language=own.language,
        memory_owner=own.memory_owner,
        memory_write=own.memory_write,
        origin=own.origin if own.origin == "meowllm" else legacy.origin,
        unknown=own.unknown,
    )
    return merged


def validate_messages(body: dict) -> list[dict]:
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise MeowLLMContractError("messages 必须是非空数组")
    out: list[dict] = []
    for index, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise MeowLLMContractError(f"messages[{index}] 必须是对象")
        role = msg.get("role")
        if role not in ("system", "user", "assistant", "tool"):
            raise MeowLLMContractError(
                f"messages[{index}].role 非法: {role!r}")
        content = msg.get("content")
        if content is None and not msg.get("tool_calls"):
            raise MeowLLMContractError(
                f"messages[{index}] 既无 content 也无 tool_calls")
        out.append(msg)
    return out


def validate_tools(body: dict) -> tuple[list[dict] | None, Any]:
    tools = body.get("tools")
    if tools is None:
        return None, None
    if not isinstance(tools, list):
        raise MeowLLMContractError("tools 必须是数组")
    normalized: list[dict] = []
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            raise MeowLLMContractError(f"tools[{index}] 必须是对象")
        if tool.get("type", "function") != "function":
            raise MeowLLMContractError(
                f"tools[{index}].type 目前只支持 function")
        fn = tool.get("function")
        if not isinstance(fn, dict) or not fn.get("name"):
            raise MeowLLMContractError(
                f"tools[{index}].function.name 缺失")
        normalized.append(tool)
    return normalized or None, body.get("tool_choice")


def build_params(body: dict, extras: MeowLLMExtras, cfg) -> MeowLLMGenParams:
    """请求体 + extras + 配置 -> 最终生成参数。"""
    gen = cfg.section("gen")
    thinking_cfg = cfg.section("thinking")
    budgets = thinking_cfg.get("budgets") or {}

    tools, tool_choice = validate_tools(body)

    level = extras.thinking_level or normalize_level(
        thinking_cfg.get("default_level", "off")) or "off"
    budget = extras.think_budget
    if budget is None:
        budget = int(budgets.get(level, 0) or 0)

    if tools and bool(thinking_cfg.get("force_off_when_tools", True)):
        level, budget = "off", 0
    if level == "off":
        budget = 0

    max_tokens = extras.max_tokens
    if max_tokens is None:
        max_tokens = _as_int(body.get("max_tokens"), "max_tokens",
                             minimum=1, maximum=131072)
    if max_tokens is None:
        max_tokens = int(gen.get("talk_max_tokens", 256))

    context_limit = extras.context_limit or int(cfg.get("context.n_ctx", 8192))
    if max_tokens >= context_limit:
        max_tokens = max(1, context_limit // 2)

    stop = body.get("stop")
    if isinstance(stop, str):
        stop = [stop]
    elif not isinstance(stop, list):
        stop = []
    stop = [str(s) for s in stop if str(s)]
    if not stop:
        stop = [str(s) for s in (gen.get("stop") or [])]

    temperature = _as_float(body.get("temperature"), "temperature")
    if temperature is None:
        temperature = float(gen.get("temperature", 0.8))
    if not (0.0 <= temperature <= 2.0):
        raise MeowLLMContractError(f"temperature 必须在 [0,2]: {temperature}")

    top_p = _as_float(body.get("top_p"), "top_p")
    if top_p is None:
        top_p = float(gen.get("top_p", 0.9))
    if not (0.0 < top_p <= 1.0):
        raise MeowLLMContractError(f"top_p 必须在 (0,1]: {top_p}")

    top_k = _as_int(body.get("top_k"), "top_k", minimum=0, maximum=1000)
    if top_k is None:
        top_k = int(gen.get("top_k", 40))

    repeat_penalty = _as_float(body.get("repeat_penalty"), "repeat_penalty")
    if repeat_penalty is None:
        repeat_penalty = float(gen.get("repeat_penalty", 1.05))

    seed = _as_int(body.get("seed"), "seed")
    if seed is None and gen.get("seed") is not None:
        seed = int(gen["seed"])

    return MeowLLMGenParams(
        max_tokens=int(max_tokens),
        temperature=temperature,
        top_p=top_p,
        top_k=int(top_k),
        repeat_penalty=repeat_penalty,
        stop=stop,
        seed=seed,
        thinking_level=level,
        think_budget=int(budget),
        tools=tools,
        tool_choice=tool_choice,
        session_id=extras.session_id,
        context_limit=context_limit,
        priority=extras.priority or "interactive",
        language=extras.language,
        memory_owner=extras.memory_owner,
        memory_write=list(extras.memory_write or []),
        raw=body,
    )
