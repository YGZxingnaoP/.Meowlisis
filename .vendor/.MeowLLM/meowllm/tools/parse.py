# -*- coding: utf-8 -*-
"""工具调用解析与分片累积。

`MeowLLMToolCallBuilder` 是项目 `func/pipeline/llm_toolbox.py::ToolCallAccumulator`
的服务端镜像，**只用于自测交叉验证**：用它把 MeowLLM 发出的分片重新拼起来，
结果必须与项目那套累积器一致，否则说明我们发的分片形状有问题。
"""

from __future__ import annotations

import json
import re
from typing import Any

from meowllm.engine.base import KIND_TOOL_CALL, MeowLLMGenEvent

_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_SMART_QUOTES = {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"}


def parse_tool_args(raw: Any) -> dict:
    """容错解析工具参数。任何失败都返回 {}，绝不抛异常。

    容忍：空串、None、尾逗号、中文引号、单引号、被截断的尾部、多余包裹。
    """
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    text = str(raw).strip()
    if not text:
        return {}

    for old, new in _SMART_QUOTES.items():
        text = text.replace(old, new)

    attempts = [text]
    # 去掉 ```json ``` 包裹
    fenced = re.sub(r"^```[a-zA-Z0-9]*\s*|\s*```$", "", text).strip()
    if fenced != text:
        attempts.append(fenced)
    # 尾逗号
    for candidate in list(attempts):
        attempts.append(_TRAILING_COMMA.sub(r"\1", candidate))
    # 单引号 → 双引号（仅当没有双引号时）
    if '"' not in text and "'" in text:
        attempts.append(text.replace("'", '"'))
    # 截断补齐：逐步补 } 与 "
    for candidate in list(attempts):
        for suffix in ("}", "}}", '"}', '"}}', '"]}'):
            attempts.append(candidate + suffix)

    for candidate in attempts:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


class MeowLLMToolCallBuilder:
    """与项目 ToolCallAccumulator 同构的最小实现。"""

    def __init__(self):
        self._calls: dict[int, dict] = {}

    def add_event(self, event: MeowLLMGenEvent) -> None:
        if event.kind != KIND_TOOL_CALL:
            return
        idx = int(event.index)
        entry = self._calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
        if event.call_id:
            entry["id"] = event.call_id
        if event.name:
            entry["name"] = event.name
        if event.arguments_delta:
            entry["arguments"] += event.arguments_delta

    def add_delta(self, index: int, call_id: str | None = None,
                  name: str | None = None, arguments_delta: str | None = None) -> None:
        self.add_event(MeowLLMGenEvent(kind=KIND_TOOL_CALL, index=index,
                                       call_id=call_id, name=name,
                                       arguments_delta=arguments_delta))

    def has_calls(self) -> bool:
        return any(c["name"] for c in self._calls.values())

    def raw(self) -> dict[int, dict]:
        return {k: dict(v) for k, v in self._calls.items()}

    def payload(self) -> list[dict]:
        out: list[dict] = []
        for idx in sorted(self._calls):
            call = self._calls[idx]
            if not call["name"]:
                continue
            out.append({
                "id": call["id"] or f"call_{idx}",
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"] or "{}",
                },
            })
        return out

    def parsed(self) -> list[dict]:
        """payload + 解析后的参数 dict，便于自测断言。"""
        out = []
        for call in self.payload():
            out.append({
                "id": call["id"],
                "name": call["function"]["name"],
                "arguments_raw": call["function"]["arguments"],
                "arguments": parse_tool_args(call["function"]["arguments"]),
            })
        return out
