# -*- coding: utf-8 -*-
"""δ-mem 的挂载层：把 n 个 DeltaMemLayer 串到具体模型上。

职责
----
1. `attach(model)`    识别 attention 模块、装 pre-hook（拿每层输入隐状态 + RoPE 的 cos/sin）、
                      注册"带 δ-mem 的 attention 实现"并把模型切过去。
2. `write_state(...)` 把一段文本（历史/记忆）写进状态：backbone 前向采隐状态 → chunk 递推。
3. `deltas(...)`      生成时每层每步算 Δq/Δo（由 inject 里的 wrapper 调用）。
4. 存盘/读盘，让"一次写、长期用"成立。

与论文的三处工程取舍
--------------------
* **写记忆时不叠加 steering**（cfg.write_steering=False）。论文的写入循环里
  每步的 x_t 都受前面读出的 memory 影响，所以严格实现要做 T 次前向；这里用
  backbone 自己的隐状态写，代价是丢掉"写入路径的自我一致性"，换到"一次前向
  写完整段记忆"。训练与推理都这么做，因此二者一致。
* **生成期间状态冻结**。论文 §3.2 先读后写，生成时也会继续写。这里只在写记忆
  那一步更新，生成时 S 是常量 —— 换来的是 decode 每步没有递推依赖，
  CUDA Graph / 批处理都不受影响（对 MeowLLM 的双流引擎是硬需求）。
* **按 chunk 写、按整段读**。chunk = 16 token 的 SSW，等价于论文"每条消息写一次"。
"""

from __future__ import annotations

import math
import os
import time
from contextlib import contextmanager

import torch
from torch import nn

from meowllm.dmem.config import DeltaMemConfig
from meowllm.dmem.layer import DeltaMemLayer


def _text_cfg(model):
    cfg = getattr(model, "config", None)
    return getattr(cfg, "text_config", None) or cfg


class DeltaMem(nn.Module):
    """所有层的 δ-mem 参数 + 当前状态 + 挂载句柄。一个模型一个实例。"""

    def __init__(self, cfg: DeltaMemConfig | None = None) -> None:
        super().__init__()
        self.cfg = cfg or DeltaMemConfig()
        self.layers = nn.ModuleDict()
        self.states: dict[int, torch.Tensor] = {}
        self.enabled = False
        self.collecting = False
        #: True 时 wrapper 会额外留下 q / attention 输出，供量级自检用（正常关掉）
        self.debug = False
        self._hidden: dict[int, torch.Tensor] = {}
        self._hooks: list = []
        self._attn_restore: str | None = None
        #: base 实现名 -> 包装名（inject.ensure_wrapped 维护）
        self.wrapped: dict[str, str] = {}
        #: True 时 inject 的守护 hook 不补包装名（写记忆那趟要用普通 attention）
        self.bypass_impl: bool = False
        # ⚠ 不能直接把 model 赋成属性：nn.Module.__setattr__ 会把 backbone 注册成
        # 子模块，于是 dmem.parameters() 里会冒出整个 backbone（实测 766M）。
        # 放进普通 dict 就不会被 nn.Module 接管。
        self._ref: dict = {"model": None}
        self.hidden_size = 0
        self.q_dim = 0
        self.head_dim = 0
        self.n_heads = 0
        #: 挂载后由 inject 填；供 deltas() 用
        self.module_names: list[int] = []

    # ---------------------------------------------------------------- 结构
    def build(self, hidden_size: int, q_dim: int, head_dim: int,
              layer_indices=None) -> None:
        """按 backbone 的维度建参数。

        layer_indices 给出模型里**实际存在**的层号（全层 = 0..L-1）。
        cfg.layers 非空时取交集（§5.3 的插入深度消融就靠这个）。
        """
        self.hidden_size = int(hidden_size)
        self.q_dim = int(q_dim)
        self.head_dim = int(head_dim)
        self.n_heads = int(q_dim) // max(1, int(head_dim))
        available = [int(i) for i in (layer_indices or [])]
        want = tuple(int(i) for i in (self.cfg.layers or ()))
        indices = [i for i in available if i in want] if want else list(available)
        for idx in indices:
            self.layers[str(idx)] = DeltaMemLayer(
                self.hidden_size, self.q_dim, self.cfg, idx)
        self.module_names = sorted(int(k) for k in self.layers.keys())

    def layer_for(self, layer_idx: int) -> DeltaMemLayer | None:
        key = str(int(layer_idx))
        return self.layers[key] if key in self.layers else None

    def _as_dtype(self) -> torch.dtype:
        name = str(self.cfg.state_dtype or "float32")
        return {"float16": torch.float16,
                "bfloat16": torch.bfloat16}.get(name, torch.float32)

    # ---------------------------------------------------------------- 挂载
    def attach(self, model) -> dict:
        """把 δ-mem 挂到模型上（不改权重，只装 hook + 换 attention 实现）。"""
        from meowllm.dmem import inject

        cfg = _text_cfg(model)
        hidden = int(getattr(cfg, "hidden_size"))
        heads = int(getattr(cfg, "num_attention_heads"))
        head_dim = int(getattr(cfg, "head_dim", hidden // max(1, heads)))
        n_layers = int(getattr(cfg, "num_hidden_layers"))

        attn_modules = inject.find_attention_modules(model)
        if not attn_modules:
            raise RuntimeError("没找到 attention 模块（需要带 layer_idx 与 o_proj 的模块）")
        present = sorted({int(m.layer_idx) for m in attn_modules})
        if not self.layers:
            self.build(hidden, heads * head_dim, head_dim, present)
        # 参数是在 build 里建的，建完再搬到 backbone 所在的设备/精度上
        try:
            self.to(next(model.parameters()).device, dtype=torch.float32)
        except StopIteration:  # pragma: no cover
            pass
        self._ref["model"] = model
        self._hooks = inject.install_hooks(model, self, attn_modules)
        self._attn_restore = inject.install_attention(model, self)
        self._hooks.append(inject.install_guard(model, self))
        return {
            "layers": self.module_names,
            "hidden_size": self.hidden_size,
            "q_dim": self.q_dim,
            "n_params": self.n_params(),
            "attn_impl": inject.current_impl(model),
        }

    def detach(self) -> None:
        from meowllm.dmem import inject

        for handle in self._hooks:
            try:
                handle.remove()
            except Exception:  # noqa: BLE001
                pass
        self._hooks = []
        model = self._ref.get("model")
        if model is not None and self._attn_restore:
            inject.restore_attention(model, self._attn_restore)
        self._attn_restore = None
        self._hidden.clear()

    # ---------------------------------------------------------------- 状态
    def clear_state(self) -> None:
        self.states.clear()

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())

    # ------------------------------------------------------- 论文式微调接口
    def trainable_parameters(self) -> list:
        """论文式的"只训 δ-mem"：返回要交给优化器的参数列表。"""
        return [p for p in self.parameters() if p.requires_grad]

    def freeze_backbone(self, model) -> int:
        """冻结 backbone（返回被冻结的张量数）。论文 §3.6 的 φ 不动。"""
        count = 0
        for p in model.parameters():
            if p.requires_grad:
                p.requires_grad_(False)
                count += 1
        for p in self.parameters():
            p.requires_grad_(True)
        return count

    def finetune_report(self) -> dict:
        """微调前的自检：参数分组、形状、是否只有 δ-mem 可训。"""
        groups: dict[str, int] = {}
        for name, p in self.named_parameters():
            key = name.rsplit(".", 1)[-1] if not name.endswith("weight") else \
                name.split(".")[-2] + ".weight"
            groups[key] = groups.get(key, 0) + p.numel()
        return {
            "trainable": sum(p.numel() for p in self.trainable_parameters()),
            "groups": groups,
            "layers": len(self.layers),
            "rank": self.cfg.rank,
            "n_states": self.cfg.n_states,
            "chunk": self.cfg.chunk,
        }

    def param_report(self) -> dict:
        total = self.n_params()
        model = self._ref.get("model")
        base = 0
        try:
            if model is not None and callable(getattr(model, "num_parameters", None)):
                base = int(model.num_parameters())
        except Exception:  # noqa: BLE001
            base = 0
        return {
            "delta_mem_params": total,
            "layers": len(self.layers),
            "rank": self.cfg.rank,
            "n_states": self.cfg.n_states,
            "chunk": self.cfg.chunk,
            "backbone_params": base,
            "ratio": (total / base) if base else None,
            "state_floats_per_layer": self.cfg.n_states * self.cfg.rank ** 2,
        }

    @contextmanager
    def steering(self, enabled: bool = True):
        """只在 with 块内打开 steering；退出一定还原（异常也不漏）。"""
        old = self.enabled
        self.enabled = bool(enabled)
        try:
            yield self
        finally:
            self.enabled = old

    # ------------------------------------------------------------ 注入强度
    def scale_alpha(self, scale: float) -> dict:
        """把每层的 α 乘以 `scale`（1.0 = 不动）。

        为什么需要这个：`config.yml` 里的 `alpha` **只是初始化值**。
        训练后每层都有自己的可学习标量 `log_alpha`，`steer()` 用的是
        `exp(log_alpha)`（实测 layer0 ≈ 15.97）。所以改配置的 alpha 不会改变
        任何东西 —— 想调"记忆对 attention 的影响力"，只能乘 `log_alpha`。

        这是纯推理期旋钮，不改结构、不改权重形状，可随时乘回去。
        """
        try:
            amount = float(scale)
        except (TypeError, ValueError):
            return {"applied": False, "reason": f"非法 scale: {scale!r}"}
        if amount <= 0:
            return {"applied": False, "reason": f"scale 必须 > 0: {amount}"}
        if abs(amount - 1.0) < 1e-9:
            return {"applied": False, "reason": "scale=1.0，无需调整",
                    "alpha_min": None, "alpha_max": None}
        delta = math.log(amount)
        alphas = []
        with torch.no_grad():
            for layer in self.layers.values():
                log_alpha = getattr(layer, "log_alpha", None)
                if log_alpha is None:
                    continue
                log_alpha.add_(delta)
                alphas.append(float(torch.exp(log_alpha).item()))
        return {"applied": True, "scale": amount,
                "alpha_min": round(min(alphas), 3) if alphas else None,
                "alpha_max": round(max(alphas), 3) if alphas else None,
                "layers": len(alphas)}

    # ------------------------------------------------------------ 写记忆
    @contextmanager
    def _plain_attention(self, model, steered: bool = False):
        """临时切到"普通 KV cache"可用的 attention 实现。

        为什么需要：MeowLLM 双流引擎把 `_attn_implementation` 换成了 `meowllm_ar`，
        那个实现只认自己的 `BlockCache`（按 P/T/W 三块切），喂它一个 `DynamicCache`
        会直接形状不符。而写记忆这一步只需要"一串连续 token 的前向"，用普通
        causal attention 就够（等价于引擎里只填 P 块那条快路）。
        """
        from meowllm.dmem import inject

        prev = inject.current_impl(model)
        self.bypass_impl = True
        inject.set_plain(model, inject.plain_impl(steered))
        try:
            yield
        finally:
            inject.set_plain(model, prev)
            self.bypass_impl = False

    def _capture_window(self, model, ids: torch.Tensor, past, positions):
        """跑一段前向，把每层 attention 的输入隐状态收进 self._hidden。"""
        self._hidden.clear()
        self.collecting = True
        try:
            kwargs = dict(input_ids=ids, use_cache=True,
                          position_ids=positions, past_key_values=past)
            out = model(**kwargs)
        finally:
            self.collecting = False
        return out

    def write_state(self, model, input_ids, boundaries=None, window: int | None = None,
                    device=None, keep_graph: bool = False) -> dict:
        """把一段 token 序列写进状态（论文 §3.4，SSW/chunk 化）。

        input_ids: list[int] 或 LongTensor (1, L)
        返回统计信息（token 数、段数、耗时），状态存在 self.states。

        性能：递推按 **所有层一起** 做（把 28 层堆成一个 batch 维），
        只有 C 次迭代而不是 C×28 次。实测 202 token 从 2.0s 降到 0.2s 级 ——
        逐层做时瓶颈完全是小 kernel 的启动开销，不是算力。
        """
        ids = torch.as_tensor(input_ids, dtype=torch.long)
        if ids.dim() == 2:
            ids = ids[0]
        if ids.numel() == 0:
            return {"tokens": 0, "chunks": 0, "seconds": 0.0, "layers": 0}
        if self.cfg.write_steering:
            raise NotImplementedError(
                "cfg.write_steering=True 需要逐段前向（写完一段才能算下一段的读），"
                "当前实现是一次前向采完 hidden；请保持 False")
        dev = device or next(model.parameters()).device
        ids = ids.to(dev)
        chunk = int(self.cfg.chunk)
        span = int(window or self.cfg.window or ids.numel())
        span = max(chunk, (span // chunk) * chunk)

        from transformers import DynamicCache

        started = time.perf_counter()
        past = DynamicCache()
        # 从**已有状态**出发：registry 的 append 就是把旧状态塞进 self.states 再调这里，
        # 如果这里从空 dict 开始，append 会静默退化成 replace（每轮把记忆覆盖成最后一轮）。
        state: dict[int, torch.Tensor] = {
            int(k): (v.detach().clone() if torch.is_tensor(v) else v)
            for k, v in (self.states or {}).items()}
        total_chunks = 0
        offset = 0
        while offset < ids.numel():
            piece = ids[offset:offset + span]
            positions = torch.arange(offset, offset + piece.numel(),
                                     dtype=torch.long, device=dev).unsqueeze(0)
            with torch.set_grad_enabled(bool(keep_graph)):
                with self._plain_attention(model):
                    out = self._capture_window(model, piece.unsqueeze(0), past,
                                               positions)
            past = getattr(out, "past_key_values", past)
            total_chunks += self._absorb_window(state, boundaries)
            offset += piece.numel()
            self._hidden.clear()
        self.states = state
        return {"tokens": int(ids.numel()), "chunks": int(total_chunks),
                "seconds": round(time.perf_counter() - started, 3),
                "layers": len(state)}

    def _absorb_window(self, state: dict, boundaries=None) -> int:
        """把一个窗口内各层的隐状态并进状态（层间融合递推）。"""
        keys, vals, gates, layers = [], [], [], []
        length = 0
        for idx in self.module_names:
            hidden = self._hidden.get(idx)
            if hidden is None:
                continue
            layer = self.layer_for(idx)
            _, km, vm, beta = layer.memory_vectors(hidden)
            kb, vb, bb = layer.pool_chunks(km, vm, beta, boundaries)
            keys.append(kb)
            vals.append(vb)
            gates.append(bb)
            layers.append(layer)
            length = hidden.shape[1]
        if not layers:
            return 0
        # (层, B, C, N, r)
        k_all = torch.stack(keys)
        v_all = torch.stack(vals)
        b_all = torch.stack(gates)
        depth, batch, count = k_all.shape[0], k_all.shape[1], k_all.shape[2]
        n, r = self.cfg.n_states, self.cfg.rank
        dtype = self._as_dtype()
        s = torch.zeros((depth, batch, n, r, r), dtype=dtype, device=k_all.device)
        for i, layer in enumerate(layers):
            prev = state.get(layer.layer_idx)
            if prev is not None:
                s[i] = prev.to(device=s.device, dtype=dtype)
        for j in range(count):
            kj = k_all[:, :, j]                     # (层,B,N,r)
            vj = v_all[:, :, j]
            gj = b_all[:, :, j]
            pred = torch.einsum("lbnrs,lbns->lbnr", s, kj)
            s = ((1.0 - gj).unsqueeze(-1) * s
                 + gj.unsqueeze(-1) * (vj - pred).unsqueeze(-1) * kj.unsqueeze(-2))
        for i, layer in enumerate(layers):
            state[layer.layer_idx] = s[i]
        return count

    # ------------------------------------------------------------ steering
    @torch.no_grad()
    def calibrate(self, model, sample_ids, target: float | None = None,
                  device=None) -> dict:
        """按实测把 Δq 的量级标到 cfg.init_ratio（只动 w_dq/w_do 的 scale）。

        为什么要这一步：修正量级 ≈ α·|W_Δ rt|，而 |rt| 既取决于状态本身的大小
        （|S| 由写入门 β 和写入次数决定），也取决于 r 与 N。解析估计很容易偏
        一个数量级（r=64 时实测只有目标的 1/60）。论文里 α=16 应该是配合某个
        特定初始化调出来的，这里改成"跑一次实测再定标"，换 rank / 换数据都稳。
        """
        if not self.states:
            return {"skipped": "no state"}
        from meowllm.dmem import inject

        target = float(self.cfg.init_ratio if target is None else target)
        dev = device or next(model.parameters()).device
        ids = torch.as_tensor(sample_ids, dtype=torch.long)
        if ids.dim() == 2:
            ids = ids[0]
        ratios = []
        with self.steering(True):
            self.debug = True
            try:
                with self._plain_attention(model, steered=True):
                    model(input_ids=ids.unsqueeze(0).to(dev), use_cache=False)
            finally:
                self.debug = False
        for module in inject.find_attention_modules(model):
            layer = getattr(module, "_dmem_layer", None)
            q_ref = getattr(module, "_dmem_last_q", None)
            if layer is None or q_ref is None:
                continue
            dq, _ = self.deltas(module, layer, None)
            if dq is None:
                continue
            ratio = (dq.abs().mean() / q_ref.abs().mean().clamp_min(1e-9)).item()
            if ratio > 0:
                ratios.append(ratio)
        if not ratios:
            return {"skipped": "no delta"}
        ratios.sort()
        measured = ratios[len(ratios) // 2]          # 取中位数，避开个别层的离群
        scale = target / max(measured, 1e-12)
        with torch.no_grad():
            for layer in self.layers.values():
                layer.w_dq.weight.mul_(scale)
                layer.w_do.weight.mul_(scale)
        return {"measured": measured, "target": target,
                "scale": scale, "layers": len(ratios)}

    # ------------------------------------------------------------ steering
    def deltas(self, module, layer: DeltaMemLayer, query: torch.Tensor):
        """算这一层这一步的 Δq（已按位置旋转）与 Δo。没有状态时返回 (None, None)。"""
        state = self.states.get(layer.layer_idx)
        if state is None:
            return None, None
        hidden = getattr(module, "_dmem_hidden", None)
        if hidden is None:
            return None, None
        # **状态必须搬到 hidden 所在的设备上**。
        # registry 从磁盘 `torch.load(map_location="cpu")` 读回来的状态是 CPU 张量，
        # 之前这里没搬，于是"重启后第一个带记忆的请求"必然炸：
        #   Expected all tensors to be on the same device, but got mat2 is on cuda:0,
        #   different from other tensors on cpu
        # 而同一进程里刚 write 过的用户用的是显存里的副本，所以这个问题只在
        # "进程重启后读旧状态"时暴露 —— 极容易被当成偶发。
        # 精度按 cfg.state_dtype（默认 float32）走，不要跟 hidden 的 bf16 混。
        want_dtype = self._as_dtype()
        if state.device != hidden.device or state.dtype != want_dtype:
            state = state.to(device=hidden.device, dtype=want_dtype)
        batch = hidden.shape[0]
        if state.shape[0] != batch:
            state = state.expand(batch, *state.shape[1:])
        qm = layer.query_vector(hidden)                  # (B,L,N,r)
        rt = layer.read(state, qm)                       # (B,L,N,r)
        dq_flat, do_flat = layer.steer(rt)               # (B,L,q_dim)
        shape = (batch, hidden.shape[1], self.n_heads, self.head_dim)
        dq = dq_flat.view(shape).transpose(1, 2)         # (B,H,L,D)
        do = do_flat.view(shape)                         # (B,L,H,D)
        cos, sin = getattr(module, "_dmem_rope", (None, None))
        if cos is not None:
            from meowllm.dmem.layer import apply_rope

            dq = apply_rope(dq, cos.to(dq.dtype), sin.to(dq.dtype))
        return dq, do

    # ---------------------------------------------------------------- 存盘
    def save(self, path: str, meta: dict | None = None) -> str:
        """存 δ-mem 参数（可选加状态）。状态通常单独存，因为它是"记忆"。"""
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        payload = {
            "cfg": self.cfg.to_dict(),
            "hidden_size": self.hidden_size,
            "q_dim": self.q_dim,
            "head_dim": self.head_dim,
            "layers": self.module_names,
            "meta": dict(meta or {}),
        }
        tensors = {f"w.{k}": v.detach().cpu()
                   for k, v in self.state_dict().items()}
        try:
            from safetensors.torch import save_file

            blob = dict(tensors)
            blob["__meta__"] = torch.tensor(list(str(payload).encode("utf-8")),
                                            dtype=torch.uint8)
            save_file(blob, path)
        except Exception:  # noqa: BLE001 - safetensors 不可用就退回 torch.save
            torch.save({"meta": payload, "weights": tensors}, path)
        return path

    def load(self, path: str, model=None) -> dict:
        """读 δ-mem 参数；给了 model 就顺手挂载。"""
        meta: dict = {}
        weights: dict = {}
        try:
            from safetensors.torch import load_file

            blob = load_file(path)
            raw = blob.pop("__meta__", None)
            if raw is not None:
                import ast

                meta = ast.literal_eval(bytes(raw.tolist()).decode("utf-8"))
            weights = blob
        except Exception:  # noqa: BLE001
            blob = torch.load(path, map_location="cpu", weights_only=False)
            meta = blob.get("meta") or {}
            weights = blob.get("weights") or {}
        cfg = DeltaMemConfig.from_dict(meta.get("cfg") or {})
        # 权重必须与当前 backbone 的维度/层号一致。不匹配就**现在**报错，让上层
        # 明确"这次的记忆不可用"；否则会挂上一份随机初始化参数，输出变差还没人发现。
        if model is not None:
            self._check_compatible(meta, model)
        self.cfg = cfg
        self.hidden_size = int(meta.get("hidden_size") or self.hidden_size)
        self.q_dim = int(meta.get("q_dim") or self.q_dim)
        self.head_dim = int(meta.get("head_dim") or self.head_dim)
        if not self.layers:
            self.build(self.hidden_size, self.q_dim, self.head_dim,
                       meta.get("layers") or [])
        for idx in (meta.get("layers") or []):
            key = str(idx)
            if key not in self.layers:
                self.layers[key] = DeltaMemLayer(
                    self.hidden_size, self.q_dim, cfg, int(idx))
        # 存盘时键统一加了 `w.` 前缀（见 save），载入必须剥掉。
        # 不剥的话 289 个键全部 unexpected、模块键全部 missing —— strict=False
        # 不报错，于是整份权重被静默丢弃、参数停在随机初始化上。
        weights = {(k[2:] if k.startswith("w.") else k): v
                   for k, v in weights.items()}
        missing, unexpected = self.load_state_dict(weights, strict=False)
        if missing or unexpected:
            # 有键对不上就说明权重与结构真的不一致，不能当没事发生
            raise ValueError(
                f"δ-mem 权重与模型结构不一致：{len(missing)} 个参数缺失、"
                f"{len(unexpected)} 个键多余（missing 例 {list(missing)[:3]}，"
                f"unexpected 例 {list(unexpected)[:3]}）")
        if model is not None:
            self.attach(model)
        self.n_heads = int(self.q_dim) // max(1, int(self.head_dim))
        self.module_names = sorted(int(k) for k in self.layers.keys())
        return {"missing": list(missing), "unexpected": list(unexpected),
                "meta": meta.get("meta") or {}}

    def _check_compatible(self, meta: dict, model) -> None:
        """权重里记录的 backbone 维度 vs 当前模型，不一致就拒绝加载。

        本地 0.6B（hidden=1024 / 28 层）与云端 8B（hidden=4096 / 36 层）训出来的
        是两份互不兼容的权重。混用不会报错到用户面前 —— 只会让记忆变成噪声。
        """
        text = _text_cfg(model)
        hidden = int(getattr(text, "hidden_size", 0) or 0)
        heads = int(getattr(text, "num_attention_heads", 0) or 0)
        head_dim = int(getattr(text, "head_dim", 0)
                       or (hidden // max(1, heads)))
        q_dim = heads * head_dim
        n_layers = int(getattr(text, "num_hidden_layers", 0) or 0)

        problems: list[str] = []
        want_hidden = int(meta.get("hidden_size") or 0)
        want_qdim = int(meta.get("q_dim") or 0)
        want_head = int(meta.get("head_dim") or 0)
        if want_hidden and hidden and want_hidden != hidden:
            problems.append(f"hidden_size 权重 {want_hidden} / 模型 {hidden}")
        if want_qdim and q_dim and want_qdim != q_dim:
            problems.append(f"q_dim 权重 {want_qdim} / 模型 {q_dim}")
        if want_head and head_dim and want_head != head_dim:
            problems.append(f"head_dim 权重 {want_head} / 模型 {head_dim}")
        want_layers = [int(i) for i in (meta.get("layers") or [])]
        over = [i for i in want_layers if n_layers and i >= n_layers]
        if over:
            problems.append(
                f"层号 {over[:6]}{'…' if len(over) > 6 else ''} 超出模型层数 {n_layers}")
        if problems:
            raise ValueError(
                "δ-mem 权重与当前 backbone 不匹配（" + "；".join(problems) + "）。"
                "这不是能自动修的问题：换回训练时那个 backbone，"
                "或者针对当前 backbone 重新训练一份权重。")
