# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import os
import time

import torch
from transformers import DynamicCache

from meowllm.engine.dualstream import compat
from meowllm.engine.dualstream.loop import DualStreamLoop
from meowllm.engine.dualstream.prompts import parse_tool_calls
from meowllm.engine.base import (
    KIND_CONTENT,
    KIND_FINISH,
    KIND_META,
    KIND_REASONING,
    KIND_TOOL_CALL,
    MeowLLMEngineBase,
    MeowLLMGenEvent,
    MeowLLMGenParams,
)
from meowllm.errors import MeowLLMEngineError

DEFAULT_MODEL_DIR = "models/Qwen3-0.6B"
DEFAULT_PROMPT_CAPACITY = 8192


def _tf_text_cfg(model):
    cfg = getattr(model, "config", None)
    text_cfg = getattr(cfg, "text_config", None) if cfg is not None else None
    return text_cfg if text_cfg is not None else cfg


def _apply_sampling(logits: torch.Tensor, temperature: float, top_p: float,
                    top_k: int, generator: torch.Generator | None) -> int:
    if temperature is None or temperature <= 0:
        return int(torch.argmax(logits).item())
    scaled = logits / max(float(temperature), 1e-5)
    probs = torch.softmax(scaled, dim=-1)
    if 0 < top_k < probs.numel():
        values, indices = torch.topk(probs, int(top_k))
        probs = torch.zeros_like(probs).scatter(0, indices, values)
        probs = probs / probs.sum()
    if 0 < top_p < 1.0:
        sorted_probs, sorted_idx = torch.sort(probs, descending=True)
        cumulative = torch.cumsum(sorted_probs, dim=-1)
        over = (cumulative > top_p).nonzero()
        cut = int(over[0].item()) + 1 if len(over) else len(sorted_probs)
        keep = sorted_idx[:cut]
        masked = torch.zeros_like(probs).scatter(0, keep, probs[keep])
        probs = masked / masked.sum()
    return int(torch.multinomial(probs, 1, generator=generator).item())


class PlainLoop:
    def __init__(self, model, tokenizer, device: str, params: MeowLLMGenParams,
                 talk_max: int) -> None:
        self.model = model
        self.tok = tokenizer
        self.device = device
        self.params = params
        self.talk_max = max(1, int(talk_max))
        self.cache = None
        self.ids: list[int] = []
        self.text = ""
        self.prompt_tokens = 0
        self.done = False
        self.logits: torch.Tensor | None = None
        self.stats = {"prompt_tokens": 0, "completion_tokens": 0}
        self._stop_ids = self._collect_stop_ids()
        self._stop_strings = [s for s in (params.stop or []) if s]

    def _collect_stop_ids(self) -> set[int]:
        out: set[int] = set()
        eos = getattr(self.tok, "eos_token_id", None)
        if isinstance(eos, int):
            out.add(eos)
        for text in ("<|im_end|>", "<|endoftext|>"):
            try:
                ids = self.tok.encode(text, add_special_tokens=False)
            except Exception:
                ids = []
            if len(ids) == 1:
                out.add(int(ids[0]))
        return out

    def _generator(self) -> torch.Generator | None:
        seed = self.params.seed
        if seed is None:
            return None
        gen = torch.Generator(device=self.device)
        gen.manual_seed(int(seed))
        return gen

    def reset(self, messages: list[dict], thinking: bool) -> None:
        tools = self.params.tools or None
        try:
            text = self.tok.apply_chat_template(
                messages, tools=tools, add_generation_prompt=True,
                enable_thinking=bool(thinking), tokenize=False)
        except TypeError:
            text = self.tok.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False)
        ids = self.tok(text, add_special_tokens=False)["input_ids"]
        if ids and isinstance(ids[0], list):
            ids = ids[0]
        self.ids = []
        self.text = ""
        self.done = False
        self.cache = None
        self.prompt_tokens = len(ids)
        self.stats["prompt_tokens"] = len(ids)
        input_ids = torch.tensor([ids], dtype=torch.long, device=self.device)
        with torch.no_grad():
            out = self._forward_model(input_ids)
        self.cache = getattr(out, "past_key_values", None)
        self.logits = out.logits[0, -1].float()

    def _forward_model(self, input_ids):
        kwargs = dict(input_ids=input_ids, past_key_values=self.cache, use_cache=True)
        try:
            return self.model(logits_to_keep=1, **kwargs)
        except TypeError:
            return self.model(**kwargs)

    def step(self) -> tuple[int, str] | None:
        if self.done or self.logits is None:
            return None
        if self.stats["completion_tokens"] >= self.talk_max:
            self.done = True
            return None
        token = _apply_sampling(self.logits, self.params.temperature,
                                self.params.top_p, self.params.top_k,
                                self._generator())
        if token in self._stop_ids:
            self.done = True
            return None
        with torch.no_grad():
            out = self._forward_model(
                torch.tensor([[token]], dtype=torch.long, device=self.device))
        self.cache = getattr(out, "past_key_values", self.cache)
        self.logits = out.logits[0, -1].float()
        self.ids.append(int(token))
        self.stats["completion_tokens"] = len(self.ids)
        full = self.tok.decode(self.ids, skip_special_tokens=True)
        delta = full[len(self.text):]
        self.text = full
        if any(mark and mark in self.text for mark in self._stop_strings):
            self.done = True
            return int(token), ""
        return int(token), delta


class AsyncHFEngine(MeowLLMEngineBase):
    kind = "dualstream"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self._model = None
        self._tokenizer = None
        self._model_dir = ""
        self._params_b = 0.0
        self._device = "cuda"
        self._arch = ""
        self._layer_types: list[str] = []
        self._linear_layers = 0
        self._dual_stream_supported = True
        self._vision = False

    def load(self) -> None:
        problems = compat.self_check()
        if problems:
            self._last_error = "; ".join(problems)
            raise MeowLLMEngineError("transformers 版本不满足要求：" + self._last_error,
                                     detail={"problems": problems})

        try:
            import torch as _torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except Exception as exc:
            self._last_error = f"导入 torch/transformers 失败：{exc}"
            raise MeowLLMEngineError(self._last_error) from exc

        raw_dir = str(self.cfg.get("engine.dualstream.model_dir", DEFAULT_MODEL_DIR) or "")
        model_dir = self.cfg.resolve(raw_dir) if raw_dir else self.cfg.resolve(DEFAULT_MODEL_DIR)
        single = os.path.join(model_dir, "model.safetensors")
        index = os.path.join(model_dir, "model.safetensors.index.json")
        shards = [f for f in (os.listdir(model_dir) if os.path.isdir(model_dir) else [])
                  if f.startswith("model-") and f.endswith(".safetensors")]
        if not (os.path.isfile(single) or os.path.isfile(index) or shards):
            self._last_error = (
                f"缺少权重：{model_dir} 下没有 model.safetensors、"
                f"model.safetensors.index.json 或 model-*.safetensors 分片")
            raise MeowLLMEngineError(self._last_error)

        raw_cfg = self._read_config(model_dir)
        self._arch = str((raw_cfg.get("architectures") or [""])[0])
        self._probe_arch(model_dir)

        self._device = str(self.cfg.get("engine.dualstream.device", "cuda") or "cuda")
        if self._device == "cuda" and not _torch.cuda.is_available():
            self.log.warning("CUDA 不可用，退回 CPU（会非常慢）")
            self._device = "cpu"

        dtype_name = str(self.cfg.get("engine.dualstream.dtype", "bfloat16") or "bfloat16")
        dtype = {"bfloat16": _torch.bfloat16, "float16": _torch.float16,
                 "float32": _torch.float32}.get(dtype_name, _torch.bfloat16)

        import transformers as _tf

        model_cls = getattr(_tf, self._arch, None) if self._arch else None
        if model_cls is None:
            model_cls = _tf.AutoModelForCausalLM

        self.log.info("加载 %s（%s，%s）arch=%s", model_dir, self._device, dtype_name,
                      getattr(model_cls, "__name__", self._arch or "AutoModelForCausalLM"))
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(model_dir)
            self._model = model_cls.from_pretrained(
                model_dir, dtype=dtype,
                device_map="cuda" if self._device == "cuda" else None)
            if self._device == "cpu":
                self._model = self._model.to("cpu")
            self._model.eval()
        except Exception as exc:
            self._last_error = f"加载模型失败：{exc}"
            raise MeowLLMEngineError(self._last_error) from exc

        self._model_dir = model_dir
        self._params_b = self._read_params_b(model_dir)
        self._orig_attn_impl = (getattr(_tf_text_cfg(self._model), "_attn_implementation", None)
                                or "sdpa")
        self._loaded = True
        if not self._dual_stream_supported:
            self.log.warning("模型含 %d/%d 层 linear_attention，双流不可用，仅支持单流",
                             self._linear_layers, len(self._layer_types) or 0)
        self.log.info("就绪：params=%.3fB dir=%s", self._params_b, model_dir)

    @staticmethod
    def _read_config(model_dir: str) -> dict:
        import json

        with open(os.path.join(model_dir, "config.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}

    def _probe_arch(self, model_dir: str) -> None:
        raw_cfg = self._read_config(model_dir)
        self._arch = str((raw_cfg.get("architectures") or [""])[0])
        text_cfg = raw_cfg.get("text_config")
        if not isinstance(text_cfg, dict):
            text_cfg = raw_cfg
        self._layer_types = [str(t) for t in (text_cfg.get("layer_types") or [])]
        self._linear_layers = sum(1 for t in self._layer_types if t == "linear_attention")
        self._dual_stream_supported = self._linear_layers == 0
        self._vision = isinstance(raw_cfg.get("vision_config"), dict)

    @staticmethod
    def _read_params_b(model_dir: str) -> float:
        import json

        try:
            with open(os.path.join(model_dir, "config.json"), encoding="utf-8") as fh:
                cfg = json.load(fh)
            text = cfg.get("text_config")
            if isinstance(text, dict):
                cfg = text
            hidden = int(cfg.get("hidden_size") or 0)
            layers = int(cfg.get("num_hidden_layers") or 0)
            vocab = int(cfg.get("vocab_size") or 0)
            inter = int(cfg.get("intermediate_size") or 0)
            if not (hidden and layers):
                return 0.0
            per_layer = 4 * hidden * hidden + 3 * hidden * inter
            total = per_layer * layers + 2 * vocab * hidden
            return round(total / 1e9, 3)
        except Exception:
            return 0.0

    def unload(self) -> None:
        self._model = None
        self._tokenizer = None
        try:
            import torch as _torch

            if _torch.cuda.is_available():
                _torch.cuda.empty_cache()
        except Exception:
            pass
        self._loaded = False

    def info(self) -> dict:
        if self._model_dir:
            model_dir, params_b = self._model_dir, self._params_b
        else:
            raw = str(self.cfg.get("engine.dualstream.model_dir", DEFAULT_MODEL_DIR) or "")
            model_dir = (self.cfg.resolve(raw) if raw
                         else self.cfg.resolve(DEFAULT_MODEL_DIR))
            params_b = self._read_params_b(model_dir)
        if not self._arch and os.path.isdir(model_dir):
            try:
                self._probe_arch(model_dir)
            except Exception:
                self._arch = ""
        return {
            "engine": self.kind,
            "model": os.path.basename(model_dir) or "?",
            "model_dir": model_dir,
            "params_b": params_b,
            "device": self._device,
            "architecture": self._arch,
            "linear_layers": self._linear_layers,
            "dual_stream": self._dual_stream_supported,
            "vision": self._vision,
            "mode": "dual-stream" if self._dual_stream_supported else "single-stream",
            "loaded": self._loaded,
        }

    def count_tokens(self, messages: list[dict]) -> int:
        if self._tokenizer is None:
            return 0
        try:
            text = self._tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False)
            return len(self._tokenizer.encode(text, add_special_tokens=False))
        except Exception:
            blob = "".join(str(m.get("content") or "") for m in messages)
            return max(1, int(len(blob) / 1.6))

    def _set_attn_impl(self, name: str) -> None:
        configs = [getattr(self._model, "config", None)]
        text_cfg = getattr(configs[0], "text_config", None) if configs[0] is not None else None
        if text_cfg is not None:
            configs.append(text_cfg)
        for cfg in configs:
            if cfg is not None and hasattr(cfg, "_attn_implementation"):
                cfg._attn_implementation = name

    def _n_ctx(self) -> int:
        try:
            value = int(self.cfg.get("context.n_ctx", DEFAULT_PROMPT_CAPACITY))
        except (TypeError, ValueError):
            value = DEFAULT_PROMPT_CAPACITY
        return max(1024, value)

    def _talk_max(self, params: MeowLLMGenParams) -> int:
        value = params.max_tokens or self.cfg.get("gen.talk_max_tokens", 256)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 256

    def _think_max(self, params: MeowLLMGenParams) -> int:
        level = str(params.thinking_level or "off").lower()
        if level == "off":
            return 0
        value = params.think_budget
        if not value:
            budgets = self.cfg.section("thinking").get("budgets") or {}
            value = budgets.get(level, 768)
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _make_loop(self, params: MeowLLMGenParams) -> DualStreamLoop:
        cfg = self.cfg
        language = (params.language or str(cfg.get("engine.dualstream.language", "zh")))[:2]
        return DualStreamLoop(
            model=self._model,
            tokenizer=self._tokenizer,
            language=language,
            thinker_max=self._think_max(params),
            writer_max=self._talk_max(params),
            probe_every=int(cfg.get("engine.dualstream.probe_every_tokens", 20) or 20),
            device=self._device,
            temperature=float(params.temperature),
            top_p=float(params.top_p),
            seed=params.seed,
            prompt_capacity=self._n_ctx(),
            max_segments=int(cfg.get("engine.dualstream.max_segments", 6) or 6),
            stop_after_no=int(cfg.get("engine.dualstream.stop_after_no", 2) or 2),
            probe_kind=str(cfg.get("engine.dualstream.probe_kind", "roleplay") or "roleplay"),
            fast_prefill=bool(cfg.get("engine.dualstream.fast_prefill", True)),
        )

    @staticmethod
    def _normalize_messages(messages: list[dict]) -> list[dict]:
        systems: list[str] = []
        rest: list[dict] = []
        for msg in messages or []:
            role = str(msg.get("role") or "")
            if role == "system":
                text = msg.get("content")
                if isinstance(text, str) and text.strip():
                    systems.append(text)
                continue
            rest.append(msg)
        if not systems:
            return rest
        return [{"role": "system", "content": "\n\n".join(systems)}] + rest

    async def generate(self, messages: list[dict], params: MeowLLMGenParams):
        self.require_loaded()
        messages = self._normalize_messages(messages)
        if self._think_max(params) > 0 and not self._dual_stream_supported:
            self.log.info("线性注意力模型不支持双流，本次按单流执行")
        dual_cap = int(self.cfg.get("context.dual_max_prompt_tokens", 0) or 0)
        if self._think_max(params) > 0 and dual_cap:
            try:
                used = self.count_tokens(messages)
            except Exception:
                used = 0
            if used > dual_cap:
                self.log.info("prompt %d token 超过双流上限 %d，本次走单流", used, dual_cap)
                async for event in self._generate_plain(messages, params):
                    yield event
                return
        if (self._think_max(params) <= 0 or params.tools
                or not self._dual_stream_supported):
            async for event in self._generate_plain(messages, params):
                yield event
            return
        async for event in self._generate_dual(messages, params):
            yield event

    async def _generate_plain(self, messages: list[dict], params: MeowLLMGenParams):
        started = time.perf_counter()
        self._set_attn_impl(self._orig_attn_impl)
        loop = PlainLoop(self._model, self._tokenizer, self._device, params,
                         self._talk_max(params))
        tool_mode = bool(params.tools)
        try:
            await asyncio.to_thread(loop.reset, list(messages), False)
        except Exception as exc:
            raise MeowLLMEngineError(f"构建提示词失败：{exc}") from exc

        yield MeowLLMGenEvent(kind=KIND_META, meta={
            "stage": "prefill", "prompt_tokens": loop.prompt_tokens})

        buffer = ""
        while not loop.done:
            step = await asyncio.to_thread(loop.step)
            if step is None:
                break
            token, text = step
            if not text:
                continue
            if tool_mode:
                buffer += text
                continue
            yield MeowLLMGenEvent(kind=KIND_CONTENT, text=text, stream="writer")

        if tool_mode:
            calls = parse_tool_calls(buffer)
            if calls:
                for index, call in enumerate(calls):
                    yield MeowLLMGenEvent(
                        kind=KIND_TOOL_CALL, index=index, call_id=f"call_{index}",
                        name=call["name"], arguments_delta=call["arguments"])
                finish_reason = "tool_calls"
            else:
                if buffer:
                    yield MeowLLMGenEvent(kind=KIND_CONTENT, text=buffer,
                                          stream="writer")
                finish_reason = "stop"
        else:
            finish_reason = "stop"

        yield MeowLLMGenEvent(kind=KIND_FINISH, finish_reason=finish_reason, meta={
            "engine": self.kind,
            "mode": "plain",
            "seconds": round(time.perf_counter() - started, 3),
            "prompt_tokens": loop.prompt_tokens,
            "completion_tokens": loop.stats["completion_tokens"],
            "thinking_level": "off",
        })

    async def _generate_dual(self, messages: list[dict], params: MeowLLMGenParams):
        started = time.perf_counter()
        loop = self._make_loop(params)
        step_count = 0
        budget = (self._talk_max(params) * max(1, loop.max_segments)
                  + self._think_max(params) + 16)
        has_tools = bool(getattr(params, "tools", None))

        try:
            await asyncio.to_thread(loop.reset, list(messages))
        except Exception as exc:
            self.log.warning("双流 prefill 失败（%s），本次回退单流", exc)
            async for event in self._generate_plain(messages, params):
                yield event
            return
        yield MeowLLMGenEvent(
            kind=KIND_META, meta={"stage": "prefill", "prompt_tokens": loop.prompt_tokens,
                                  "blocks": dict(
                                      (b.value, n) for b, n in loop.layout.lengths.items())})

        writer_buf = ""
        while not loop.finished and step_count < budget:
            chunks = await asyncio.to_thread(loop.step)
            step_count += 1
            for chunk in chunks:
                if chunk.stream == "thinker":
                    yield MeowLLMGenEvent(kind=KIND_REASONING, text=chunk.text,
                                          stream="thinker")
                elif chunk.stream == "writer":
                    if has_tools:
                        writer_buf += chunk.text
                    else:
                        yield MeowLLMGenEvent(kind=KIND_CONTENT, text=chunk.text,
                                              stream="writer")
                elif chunk.stream == "mode":
                    yield MeowLLMGenEvent(kind=KIND_META, meta=chunk.detail)

        finish_reason = "stop"
        if has_tools:
            calls = parse_tool_calls(writer_buf)
            if calls:
                for index, call in enumerate(calls):
                    yield MeowLLMGenEvent(
                        kind=KIND_TOOL_CALL, index=index,
                        call_id=f"call_{index}",
                        name=call["name"], arguments_delta=call["arguments"])
                finish_reason = "tool_calls"
            elif writer_buf:
                yield MeowLLMGenEvent(kind=KIND_CONTENT, text=writer_buf,
                                      stream="writer")

        stats = loop.stats
        yield MeowLLMGenEvent(kind=KIND_FINISH, finish_reason=finish_reason, meta={
            "engine": self.kind,
            "mode": "dual",
            "seconds": round(time.perf_counter() - started, 3),
            "steps": step_count,
            "prompt_tokens": loop.prompt_tokens,
            "completion_tokens": stats.writer_tokens,
            "reasoning_tokens": stats.thinker_tokens,
            "writer_tokens": stats.writer_tokens,
            "thinker_tokens": stats.thinker_tokens,
            "thinker_ahead": stats.thinker_ahead,
            "pauses": stats.pauses,
            "resumes": stats.resumes,
            "probes": stats.probes,
            "probe_no": stats.probe_no,
            "segments": stats.segments,
            "segment_texts": list(getattr(loop, "segment_texts", [])),
            "thinker_stop": loop.thinker_stop,
            "thinking_level": params.thinking_level,
        })

    def kv_slot_stats(self) -> dict:
        return {"supported": False, "reason": "dualstream 自己管理 KV 块"}
