# -*- coding: utf-8 -*-
"""Stub 引擎：不加载任何权重，按配置产出可控的时序与形状。

用途
----
本机唯一允许的"零模型"引擎。它不是一个假回复机器，而是**契约与缓存账本的
发生器**：能精确控制是否吐 reasoning_content、工具调用分几片、每片多长、
每片间隔多久，从而在不下载任何模型的前提下验证：

  * OpenAI 流式分片形状能否被项目 ToolCallAccumulator 正确合并
  * 思考预算是否被强制执行
  * 前缀/会话缓存记账是否准确
  * MIRROR 状态机是否会卡死
"""

from __future__ import annotations

import asyncio
import json
import time

from meowllm.engine.base import (
    CHARS_PER_TOKEN,
    KIND_CONTENT,
    KIND_FINISH,
    KIND_META,
    KIND_REASONING,
    KIND_TOOL_CALL,
    MeowLLMEngineBase,
    MeowLLMGenEvent,
    MeowLLMGenParams,
)


class MeowLLMEngineStub(MeowLLMEngineBase):
    kind = "stub"

    def __init__(self, cfg):
        super().__init__(cfg)
        self._stub = cfg.section("stub")
        self._loaded_at = 0.0

    # ---------------- 生命周期 ----------------
    def load(self) -> None:
        self._loaded = True
        self._loaded_at = time.time()
        self.log.warning("STUB 模式：未加载任何权重（仅契约与缓存记账）")

    def info(self) -> dict:
        return {
            "engine": "stub",
            "model": self.cfg.get("model.name"),
            "params_b": 0.0,
            "quant": "none",
            "n_ctx": self.cfg.get("context.n_ctx"),
            "loaded": self._loaded,
            "note": "stub 不加载权重",
        }

    # ---------------- 计数 ----------------
    def count_tokens(self, messages: list[dict]) -> int:
        chars = 0
        for msg in messages or []:
            content = msg.get("content")
            if isinstance(content, str):
                chars += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        chars += len(str(part.get("text") or ""))
                    elif isinstance(part, dict):
                        chars += 64  # 图片等非文本块按固定成本估
            for tool_call in (msg.get("tool_calls") or []):
                chars += len(json.dumps(tool_call, ensure_ascii=False))
        return max(1, int(round(chars / CHARS_PER_TOKEN)))

    # ---------------- 生成 ----------------
    async def generate(self, messages: list[dict],
                       params: MeowLLMGenParams):
        self.require_loaded()

        chunk_chars = max(1, int(self._stub.get("chunk_chars", 4)))
        delay = max(0.0, float(self._stub.get("chunk_delay_ms", 15)) / 1000.0)
        emit_reasoning = bool(self._stub.get("emit_reasoning", True))
        reasoning_chars = max(0, int(self._stub.get("reasoning_chars", 120)))
        split_args = max(1, int(self._stub.get("split_arguments", 12)))
        reply = str(self._stub.get("reply", "喵~（MeowLLM stub 回复）"))
        parallel = max(1, int(self._stub.get("parallel_tools", 1)))
        sim = self._stub.get("sim") or {}
        prefill_tps = float(sim.get("prefill_tps", 1200) or 1200)
        decode_tps = float(sim.get("decoded_tps", sim.get("decode_tps", 30)) or 30)

        prompt_tokens = self.count_tokens(messages)
        started = time.perf_counter()

        # ---- 1) 思考（受 think_budget 硬强制） ----
        emitted_reasoning = 0
        if emit_reasoning and params.thinking_level != "off" and params.think_budget > 0:
            budget_chars = int(params.think_budget * CHARS_PER_TOKEN)
            target = min(reasoning_chars, budget_chars)
            text = ("思考中……" * (target // 4 + 2))[:target]
            for piece in self._iter_text_chunks(text, chunk_chars):
                emitted_reasoning += 1
                yield MeowLLMGenEvent(kind=KIND_REASONING, text=piece)
                if delay:
                    await asyncio.sleep(delay)

        # ---- 2) 工具调用 ----
        tool_calls = self._build_tool_calls(params, parallel, split_args)
        for index, (call_id, name, arguments) in enumerate(tool_calls):
            yield MeowLLMGenEvent(kind=KIND_TOOL_CALL, index=index,
                                  call_id=call_id, name=name,
                                  arguments_delta="")
            for piece in self._iter_text_chunks(arguments, split_args):
                yield MeowLLMGenEvent(kind=KIND_TOOL_CALL, index=index,
                                      arguments_delta=piece)
                if delay:
                    await asyncio.sleep(delay)

        # ---- 3) 正文 ----
        content_chars = 0
        if not tool_calls:
            for piece in self._iter_text_chunks(reply, chunk_chars):
                content_chars += len(piece)
                yield MeowLLMGenEvent(kind=KIND_CONTENT, text=piece)
                if delay:
                    await asyncio.sleep(delay)

        total_ms = (time.perf_counter() - started) * 1000.0
        prefill_ms = prompt_tokens / max(1.0, prefill_tps) * 1000.0
        decode_tokens = max(1, int(round((content_chars + emitted_reasoning * chunk_chars)
                                         / CHARS_PER_TOKEN)))
        yield MeowLLMGenEvent(
            kind=KIND_FINISH,
            finish_reason="tool_calls" if tool_calls else "stop",
        )
        yield MeowLLMGenEvent(kind=KIND_META, meta={
            "engine": "stub",
            "simulated": True,
            "prompt_tokens": prompt_tokens,
            "prefill_tps": prefill_tps,
            "decode_tps": decode_tps,
            "prefill_ms": round(prefill_ms, 3),
            "generation_ms": round(total_ms, 3),
            "completion_tokens": decode_tokens,
            "think_tokens": int(round(emitted_reasoning * chunk_chars / CHARS_PER_TOKEN)),
            "think_budget": params.think_budget,
            "truncated_history": 0,
        })

    # ---------------- 工具调用构造 ----------------
    def _build_tool_calls(self, params: MeowLLMGenParams,
                          parallel: int, split_args: int):
        """返回 [(call_id, name, arguments_json)]。

        优先级：
          1) 请求强制 tool_choice      -> 只吐该函数
          2) 配置了 stub.tool_call     -> 按配置（可 parallel_extra 造多工具）
          3) 带 tools 但未配置         -> 默认给第一个工具造一份合规参数
        """
        configured = self._stub.get("tool_call")
        forced = self._forced_name(params.tool_choice)

        if forced:
            if isinstance(configured, dict) and configured.get("name") == forced:
                args = configured.get("arguments") or {}
            else:
                args = self._synth_args(forced, params.tools)
            return [("call_stub_0", forced, json.dumps(args, ensure_ascii=False))]

        if not params.has_tools:
            return []

        if isinstance(configured, dict) and configured.get("name"):
            names = [str(configured["name"])]
            for extra in (configured.get("parallel_extra") or []):
                if len(names) >= parallel:
                    break
                names.append(str(extra))
            args = configured.get("arguments") or {}
            return [(f"call_stub_{i}", name, json.dumps(args, ensure_ascii=False))
                    for i, name in enumerate(names)]

        first = self._first_tool_name(params.tools)
        if not first:
            return []
        args = self._synth_args(first, params.tools)
        return [("call_stub_0", first, json.dumps(args, ensure_ascii=False))]

    @staticmethod
    def _first_tool_name(tools) -> str:
        for tool in (tools or []):
            fn = (tool or {}).get("function") or {}
            if fn.get("name"):
                return str(fn["name"])
        return ""

    @staticmethod
    def _synth_args(name: str, tools) -> dict:
        """按工具的 parameters.required 造一份类型合规的占位参数。"""
        schema: dict = {}
        for tool in (tools or []):
            fn = (tool or {}).get("function") or {}
            if fn.get("name") == name:
                schema = fn.get("parameters") or {}
                break
        props = schema.get("properties") or {}
        required = schema.get("required") or list(props)
        placeholders = {
            "string": "stub", "number": 0.5, "integer": 1,
            "boolean": True, "array": [], "object": {},
        }
        out: dict = {}
        for key in required:
            spec = props.get(key) or {}
            out[str(key)] = placeholders.get(str(spec.get("type") or "string"), "stub")
        return out

    @staticmethod
    def _forced_name(tool_choice) -> str | None:
        if isinstance(tool_choice, dict):
            fn = tool_choice.get("function")
            if isinstance(fn, dict) and fn.get("name"):
                return str(fn["name"])
            if tool_choice.get("name"):
                return str(tool_choice["name"])
        return None
