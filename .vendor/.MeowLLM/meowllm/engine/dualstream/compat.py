# -*- coding: utf-8 -*-
"""版本适配层：**只有这个文件知道 transformers 的内部 API**。

为什么单独一层
--------------
AsyncReasoning 需要三个插槽：
    1. attention 派发表（注册自定义实现）
    2. Cache 基类（自定义三块 KV）
    3. attention 函数的调用契约

这三处在 4.x / 5.x 之间都不一样，而且会随小版本漂移。把它们收在这一个文件里，
其它模块只调用本文件导出的函数；将来换版本只需要改这里。

本文件**不在 import 时访问模型**，也不假设 API 一定存在 ——
缺失时由 `self_check()` 统一报告，避免"解码到第 5 步才炸"。
"""

from __future__ import annotations

from typing import Callable

# ------------------------------------------------------------------ 导入
_TRANSFORMERS_ERROR: str | None = None

ALL_ATTENTION_FUNCTIONS = None
try:
    from transformers.modeling_utils import ALL_ATTENTION_FUNCTIONS  # type: ignore[assignment]
except Exception as exc:  # pragma: no cover
    _TRANSFORMERS_ERROR = f"无法导入 ALL_ATTENTION_FUNCTIONS: {exc}"

CacheBase = None
try:
    from transformers import Cache as CacheBase  # type: ignore[assignment]
except Exception as exc:  # pragma: no cover
    CacheBase = None
    _TRANSFORMERS_ERROR = (_TRANSFORMERS_ERROR or "") + f" | 无法导入 Cache: {exc}"

#: 我们在派发表里注册的名字
ATTN_NAME = "meowllm_ar"


def register_attention(name: str, fn: Callable) -> None:
    """把自定义 attention 注册进 transformers 的派发表。

    5.x 的 `AttentionInterface` 继承 `GeneralInterface`，其 `register` 在不同小版本
    里既可能是 `register(name, fn)`，也可能是可当装饰器用的 `register(name)`。
    这里两种都试，失败则直接写底层映射，保证可用。
    """
    if ALL_ATTENTION_FUNCTIONS is None:
        raise RuntimeError(f"transformers 的 attention 派发表不可用：{_TRANSFORMERS_ERROR}")

    register = getattr(ALL_ATTENTION_FUNCTIONS, "register", None)
    if callable(register):
        try:
            register(name, fn)
            return
        except TypeError:
            try:
                register(name)(fn)  # 装饰器形态
                return
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
    ALL_ATTENTION_FUNCTIONS[name] = fn  # type: ignore[index]


def set_attn_impl(model, name: str = ATTN_NAME) -> None:
    """让模型走我们注册的实现。

    必须在 `register_attention` 之后调用：5.x 的 `get_interface` 对未注册的名字
    会直接抛 KeyError（只有 "eager" 例外）。
    """
    if ALL_ATTENTION_FUNCTIONS is not None and name != "eager":
        if name not in ALL_ATTENTION_FUNCTIONS:  # type: ignore[operator]
            raise RuntimeError(
                f"attention 实现 {name!r} 尚未注册；请先调用 register_attention()")
    model.config._attn_implementation = name  # noqa: SLF001 - 这就是公开入口


def get_attn_impl(model) -> str:
    """读当前 attention 实现名（调试用）。"""
    return str(getattr(model.config, "_attn_implementation", "?"))


def encode_chat(tokenizer, messages: list[dict]) -> list[int]:
    """把 messages 渲染成 token id 列表。

    为什么需要这层包装：transformers 5.x 的 `apply_chat_template(tokenize=True)`
    返回 `BatchEncoding`（类字典），而 `return_tensors="pt"` 的行为也变了。
    直接 `list(...)` 会迭代出键名（字符串），继而报
    `ValueError: too many dimensions 'str'`。
    这里把三种可能形态（BatchEncoding / 嵌套列表 / token 字符串列表）都归一。
    """
    out = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True)

    if hasattr(out, "keys"):                     # BatchEncoding / dict
        ids = out["input_ids"]
    else:
        ids = out

    seq = list(ids)
    if seq and isinstance(seq[0], (list, tuple)):  # batch 维多余 → 取第一条
        seq = list(seq[0])
    if seq and isinstance(seq[0], str):            # 拿到的是 token 字面量
        seq = tokenizer.convert_tokens_to_ids(seq)
    return [int(x) for x in seq]


def self_check() -> list[str]:
    """启动即验：缺什么就明确报什么。

    返回问题列表；空列表表示可用。
    """
    problems: list[str] = []
    if ALL_ATTENTION_FUNCTIONS is None:
        problems.append(f"attention 派发表不可用（{_TRANSFORMERS_ERROR}）")
    elif not hasattr(ALL_ATTENTION_FUNCTIONS, "__setitem__"):
        problems.append("attention 派发表不可写，无法注册自定义实现")

    if CacheBase is None:
        problems.append(f"transformers.Cache 不可用（{_TRANSFORMERS_ERROR}）")
    elif not hasattr(CacheBase, "update"):
        problems.append("transformers.Cache 缺少 update()，与 5.x 契约不符")

    try:
        import transformers

        version = transformers.__version__
    except Exception:  # noqa: BLE001
        version = "?"

    if problems:
        problems.append(
            f"当前 transformers = {version}；建议 4.5x 或 5.3+"
            "（见 docs/notes/TRANSFORMERS_5x_适配清单.md）")
    return problems
