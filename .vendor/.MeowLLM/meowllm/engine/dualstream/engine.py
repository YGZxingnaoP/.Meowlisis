# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import hashlib
import os
import time

import torch

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
from meowllm.errors import MeowLLMContractError, MeowLLMEngineError

DEFAULT_MODEL_DIR = "models/Qwen3-0.6B"
DEFAULT_PROMPT_CAPACITY = 8192


def _tf_text_cfg(model):
    cfg = getattr(model, "config", None)
    text_cfg = getattr(cfg, "text_config", None) if cfg is not None else None
    return text_cfg if text_cfg is not None else cfg


def _parse_layers(value) -> tuple:
    """`"8-19"` / `"0,5,9"` / `""`（= 全层）-> 层号元组。"""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(int(x) for x in value)
    text = str(value).strip()
    if not text:
        return ()
    if "-" in text:
        lo, hi = text.split("-", 1)
        return tuple(range(int(lo), int(hi) + 1))
    return tuple(int(x) for x in text.split(",") if x.strip())


def _file_sha1(path: str, limit: int = 64 << 20) -> str:
    """权重指纹（只读前 64MB，秒级；用于"状态与权重是否配套"的校验）。"""
    try:
        digest = hashlib.sha1()
        with open(path, "rb") as fh:
            remain = limit
            while remain > 0:
                chunk = fh.read(min(1 << 20, remain))
                if not chunk:
                    break
                digest.update(chunk)
                remain -= len(chunk)
        return digest.hexdigest()[:16]
    except OSError:
        return ""


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
        if full.endswith("\ufffd"):
            # 中文一个字符常横跨 2~3 个字节级 token：此刻解出来末尾还是半个字，
            # transformers 只能给 U+FFFD。**先别吐**，等下一个 token 补齐再一起发
            # —— 否则输出里会出现"推"变成"�"这种乱码（实测很常见）。
            return int(token), ""
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
        #: δ-mem（`memory.delta_mem.enabled` 时才非 None）
        self.dmem = None
        self.dmem_registry = None
        #: 为什么没挂上（"没开" / 权重缺失 / 形状不匹配 …）；对外经 dmem_status 暴露
        self._dmem_reason = ""
        #: 上一次生成用了谁的记忆（只做观测）
        self._last_memory: dict = {}

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
        self._load_delta_mem()

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

    # ------------------------------------------------------------ δ-mem
    def _load_delta_mem(self) -> None:
        """按 `memory.delta_mem` 挂载 δ-mem。

        失败一律降级成"不挂记忆"：这是记忆增强，不是主链路，不能因为权重/路径
        有问题就让整个本地模型起不来。但**降级原因必须留住**（`self._dmem_reason`），
        否则运维只能看到 `enabled: false`，分不清"没开"和"开了但挂了"。
        """
        node = self.cfg.section("memory").get("delta_mem") or {}
        if not node.get("enabled"):
            self._dmem_reason = "config 里 memory.delta_mem.enabled=false（没开，不是出错）"
            return
        try:
            from meowllm.dmem import DeltaMem, DeltaMemConfig
            from meowllm.dmem.registry import DmemRegistry

            weights = self.cfg.resolve(str(node.get("weights") or ""))
            cfg = DeltaMemConfig(
                rank=int(node.get("rank", 64)),
                n_states=int(node.get("n_states", 1)),
                chunk=int(node.get("chunk", 16)),
                alpha=float(node.get("alpha", 16.0)),
                layers=_parse_layers(node.get("layers")),
                # 写记忆那趟前向的窗口。留空 = 跟上下文窗口一致；但训练时的窗口
                # 通常是 512~1024，这里给出显式可配项（不是结构参数，只影响写入分块）。
                window=int(node.get("window") or 0)
                or int(self.cfg.get("context.n_ctx", 8192) or 8192),
            )
            dmem = DeltaMem(cfg)
            if weights and os.path.isfile(weights):
                dmem.load(weights, model=self._model)
            elif node.get("allow_untrained"):
                self.log.warning(
                    "δ-mem 权重不存在（%s），按**未训练**随机初始化挂载 —— "
                    "只在验管道时这么用，效果一定比不挂更差", weights or "(空)")
                dmem.attach(self._model)
            else:
                # 默认不挂：随机初始化的 Δ-mem 会往 attention 里注入噪声，
                # 比"没有记忆"更糟，而且从外面完全看不出来。
                raise FileNotFoundError(
                    f"δ-mem 权重不存在：{weights or '(config 里 weights 为空)'}；"
                    "确实要用未训练权重验管道，就把 memory.delta_mem.allow_untrained 设成 true")
            dmem.cfg = cfg
            # 注入强度缩放：config 的 alpha 只是初始化值，真正生效的是每层学出来的
            # log_alpha（≈16）。要调"记忆对 attention 的影响力"只能乘它。
            alpha_scale = float(node.get("alpha_scale", 1.0) or 1.0)
            if alpha_scale != 1.0:
                info = dmem.scale_alpha(alpha_scale)
                self.log.info("δ-mem 注入强度 ×%g：%s", alpha_scale, info)
            report = dmem.param_report()
            self.log.info("δ-mem 已挂载：%d 层 r=%d N=%d chunk=%d，%.2fM 参数（%.2f%%）",
                          len(dmem.module_names), cfg.rank, cfg.n_states, cfg.chunk,
                          report["delta_mem_params"] / 1e6,
                          (report["ratio"] or 0) * 100)
            state_dir = self.cfg.resolve(str(node.get("state_dir") or "")
                                         or "character/memory/.dmem")
            userinfo = self.cfg.resolve(str(node.get("userinfo_dir") or "")
                                        or os.path.join("..", "..", "character",
                                                        "userinfo"))
            self.dmem_registry = DmemRegistry(
                dmem,
                layout=str(node.get("layout") or "userinfo"),
                userinfo_dir=userinfo,
                flat_dir=state_dir,
                formal_pattern=str(node.get("formal_pattern") or r"^\d{6}$"),
                strict_formal=bool(node.get("strict_formal", True)),
                max_cached=int(node.get("max_cached_owners", 8)),
                persist=bool(node.get("persist", True)),
                weights_sha1=_file_sha1(weights) if os.path.isfile(weights) else "",
                backup_keep=int(node.get("backup_keep", 5)))
            self.log.info("δ-mem 状态存储：layout=%s root=%s（每用户独立目录）",
                          self.dmem_registry.layout, self.dmem_registry._root())
            self.dmem = dmem
            self._dmem_reason = ""
            if node.get("calibrate_on_load"):
                self.log.info("δ-mem 定标：%s", dmem.calibrate(self._model))
        except Exception as exc:  # noqa: BLE001
            self.log.warning("δ-mem 挂载失败，本次按无记忆运行：%s", exc)
            # 这两类异常的消息本身就是给人看的完整说明，不必再叠一层类型名
            self._dmem_reason = (str(exc)
                                 if isinstance(exc, (ValueError, FileNotFoundError))
                                 else f"{type(exc).__name__}: {exc}")
            self.dmem = None
            self.dmem_registry = None

    @property
    def dmem_ready(self) -> bool:
        return self.dmem is not None and self.dmem_registry is not None

    def dmem_status(self) -> dict:
        if not self.dmem_ready:
            return {"enabled": False,
                    "reason": self._dmem_reason or "未挂载（原因未记录）"}
        return {"enabled": True,
                "params": self.dmem.param_report(),
                "config": self.dmem.cfg.to_dict(),
                "registry": self.dmem_registry.stats()}

    def dmem_write(self, owner: str, text: str, mode: str = "replace",
                   source: str = "api") -> dict:
        """把文本写进某 owner 的状态（等价 mem0 的 add）。"""
        if not self.dmem_ready:
            raise MeowLLMEngineError(
                f"δ-mem 未挂载（{self._dmem_reason or '原因未记录'}）")
        if not str(owner or "").strip():
            raise MeowLLMContractError("owner 不能为空")
        ids = self._tokenizer.encode(text or "", add_special_tokens=False)
        if not ids:
            raise MeowLLMContractError("text 为空")
        stat = self.dmem_registry.write(owner, ids, self._model, device=self._device,
                                        mode=mode, source_text=text or "",
                                        source_tag=str(source or "api"))
        self.log.info("δ-mem 写入 owner=%s %s：%d token / %d 段，%ss",
                      owner, mode, stat.get("tokens"), stat.get("chunks"),
                      stat.get("seconds"))
        return stat

    def dmem_forget(self, owner: str) -> dict:
        if not self.dmem_ready:
            raise MeowLLMEngineError(
                f"δ-mem 未挂载（{self._dmem_reason or '原因未记录'}）")
        return {"owner": owner, "removed": bool(self.dmem_registry.forget(owner))}

    @property
    def tokenizer(self):
        return self._tokenizer

    def unload(self) -> None:
        try:
            if self.dmem is not None:
                self.dmem.detach()
        except Exception:  # noqa: BLE001
            pass
        self.dmem = None
        self.dmem_registry = None
        self._dmem_reason = "引擎已卸载"
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
        return DualStreamLoop(
            model=self._model,
            tokenizer=self._tokenizer,
            thinker_max=self._think_max(params),
            writer_max=self._talk_max(params),
            probe_every=int(cfg.get("engine.dualstream.probe_every_tokens", 20) or 20),
            device=self._device,
            temperature=float(params.temperature),
            top_p=float(params.top_p),
            seed=params.seed,
            prompt_capacity=self._n_ctx(),
            pause_on_paragraph=bool(
                cfg.get("engine.dualstream.pause_on_paragraph", True)),
            yes_bias=float(cfg.get("engine.dualstream.yes_bias", 0.0) or 0.0),
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

    def _apply_memory(self, params: MeowLLMGenParams) -> dict:
        """按本次请求切到对应 owner 的记忆状态（没有 owner 就关掉 steering）。"""
        if not self.dmem_ready:
            return {"attached": False, "reason": "未挂载"}
        if not params.memory_owner:
            self.dmem_registry.use(None)
            return {"attached": False, "reason": "no-owner"}
        # **工具回合不挂记忆**（协议级规则，不是某个客户端的责任）。
        # 实测：同一段 200 条消息 + 工具定义 + 同一条指令
        #     无记忆      → finish=tool_calls，结构化调用 ✓
        #     带记忆 α×1 → finish=stop，正文里出现 qq_send_message{"contact":...}
        #     带记忆 α×4 → 重复死循环
        # δ-mem 的注入会扰动回复开头的 <tool_call> 标记，导致格式不合法、
        # parse_tool_calls 认不出，整段被当正文发出，工具从未执行。
        # 放在这里而不是客户端，是为了让**任何**调用方（含 curl / 脚本 / 未来新平台）
        # 都自动守规矩，客户端不需要知道 δ-mem 的存在。
        if params.tools:
            self.dmem_registry.use(None)
            return {"attached": False, "reason": "tools",
                    "owner": params.memory_owner, "tool_count": len(params.tools)}
        info: dict = {"owner": params.memory_owner}
        try:
            if params.memory_write:
                text = "\n".join(t for t in params.memory_write if t)
                mode = "append" if self.dmem_registry.exists(params.memory_owner) else "replace"
                info["write"] = self.dmem_write(params.memory_owner, text, mode=mode)
            info["attached"] = bool(self.dmem_registry.use(params.memory_owner))
        except Exception as exc:  # noqa: BLE001 - 记忆出问题不能影响出字
            self.log.warning("δ-mem 准备失败（owner=%s）：%s", params.memory_owner, exc)
            self.dmem_registry.use(None)
            info["attached"] = False
            info["error"] = str(exc)
        return info

    async def generate(self, messages: list[dict], params: MeowLLMGenParams):
        self.require_loaded()
        messages = self._normalize_messages(messages)
        memory = self._apply_memory(params)
        self._last_memory = memory
        if memory.get("owner"):
            self.log.info("δ-mem owner=%s attached=%s", memory.get("owner"),
                          memory.get("attached"))
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
            "memory": getattr(self, "_last_memory", {}),
        })

    async def _generate_dual(self, messages: list[dict], params: MeowLLMGenParams):
        started = time.perf_counter()
        loop = self._make_loop(params)
        step_count = 0
        # 一个 step 最多推进 thinker / writer 各 1 个 token → 上界就是两者之和
        budget = loop.thinker_max + loop.writer_max + 32

        try:
            await asyncio.to_thread(loop.reset, list(messages))
        except Exception as exc:
            self.log.warning("双流 prefill 失败（%s），本次回退单流", exc)
            async for event in self._generate_plain(messages, params):
                yield event
            return
        yield MeowLLMGenEvent(
            kind=KIND_META, meta={"stage": "prefill", "prompt_tokens": loop.prompt_tokens,
                                  "blocks": {b.value: n for b, n in
                                             loop.layout.lengths.items()}})

        while not loop.finished and step_count < budget:
            chunks = await asyncio.to_thread(loop.step)
            step_count += 1
            for chunk in chunks:
                if chunk.stream == "thinker":
                    yield MeowLLMGenEvent(kind=KIND_REASONING, text=chunk.text,
                                          stream="thinker")
                elif chunk.stream == "writer":
                    yield MeowLLMGenEvent(kind=KIND_CONTENT, text=chunk.text,
                                          stream="writer")
                else:
                    yield MeowLLMGenEvent(kind=KIND_META, meta=chunk.detail)

        stats = loop.stats
        truncated = loop.finish_reason == "length"
        yield MeowLLMGenEvent(
            kind=KIND_FINISH,
            finish_reason="length" if truncated else "stop",
            meta={
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
                "pause_thoughts": stats.pause_thoughts,
                "pause_paragraph": stats.pause_paragraph,
                "thinker_stop": loop.thinker_stop,
                "thinking_level": params.thinking_level,
                "memory": getattr(self, "_last_memory", {}),
            })

    def kv_slot_stats(self) -> dict:
        return {"supported": False, "reason": "dualstream 自己管理 KV 块"}
