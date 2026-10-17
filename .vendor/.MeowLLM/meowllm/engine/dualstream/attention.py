# -*- coding: utf-8 -*-
"""自定义 attention：按块给 query 补角度，其余与 eager 一致。

挂在 transformers 的派发表上（名字见 compat.ATTN_NAME）。调用契约由
`Qwen3Attention.forward` 决定（5.x）：

    attention_interface(module, query, key, value, attention_mask,
                        dropout=..., scaling=..., sliding_window=..., **kwargs)

其中 `key`/`value` 是 `past_key_values.update()` 的返回值 —— 也就是
`BlockCache` 按当前视图顺序拼接好的三块，所以这里只要按块切片即可。

两种阶段用同一个函数
--------------------
* **prefill**（query 长度 > 1）：只有 P 块，delta 全为 0，使用模型给的因果掩码
* **decode**（query 长度 == 1）：新 token 在视图里永远是最末尾，
  因此它能看到全部缓存 —— 不需要掩码，直接全注意力

这个判据很稳：我们每步每视图只追加 1 个 token，prefill 只会发生在建 P 时。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

from meowllm.engine.dualstream.blocks import Block, BlockLayout, View, block_slices
from meowllm.engine.dualstream.compat import ATTN_NAME, register_attention
from meowllm.engine.dualstream.rope import DeltaRotator


@dataclass
class ARContext:
    """一次 forward 的上下文。

    引擎在每次前向前把 `view` / `own_block` 改好；所有层的 attention 共享
    同一个对象，所以不会出现"层与层看到不同视图"。
    """

    layout: BlockLayout
    rotator: DeltaRotator
    view: View = View.WRITER
    own_block: Block = Block.WRITER
    fast_prefill: bool = True


def repeat_kv(hidden_states: torch.Tensor, n_rep: int) -> torch.Tensor:
    """GQA 展开：把 n_kv 头复制成 n_q 头。

    5.x 把这一步移进了各 attention 实现内部（见 integrations/sdpa_attention.py），
    自定义实现必须自己做，否则形状不匹配或静默算错。
    """
    if n_rep == 1:
        return hidden_states
    batch, num_kv_heads, slen, head_dim = hidden_states.shape
    hidden_states = hidden_states[:, :, None, :, :].expand(
        batch, num_kv_heads, n_rep, slen, head_dim)
    return hidden_states.reshape(batch, num_kv_heads * n_rep, slen, head_dim)


def _eager_plain(query, key, value, attention_mask, scaling):
    """不涉及块的普通 eager attention（兜底路径）。"""
    scores = torch.matmul(query, key.transpose(2, 3)) * scaling
    if attention_mask is not None:
        scores = scores + attention_mask
    probs = torch.softmax(scores, dim=-1, dtype=torch.float32).to(query.dtype)
    return torch.matmul(probs, value)


def ar_attention_forward(
    module,
    query: torch.Tensor,
    key: torch.Tensor,
    value: torch.Tensor,
    attention_mask: torch.Tensor | None,
    dropout: float = 0.0,
    scaling: float | None = None,
    sliding_window: int | None = None,
    **kwargs,
):
    """AsyncReasoning 的 attention 实现。返回 (attn_output, attn_weights=None)。"""
    ctx: ARContext | None = getattr(module, "_meowllm_ctx", None)
    if scaling is None:
        scaling = getattr(module, "scaling", None) or (
            1.0 / math.sqrt(query.shape[-1]))

    # 没有上下文（例如别人直接加载了这个模型）→ 退回普通注意力，绝不崩
    if ctx is None:
        return _eager_plain(query, key, value, attention_mask, scaling), None

    # GQA 展开
    n_rep = int(getattr(module, "num_key_value_groups", 1) or 1)
    key = repeat_kv(key, n_rep)
    value = repeat_kv(value, n_rep)

    layout = ctx.layout
    view = ctx.view
    qlen = query.shape[2]
    is_decode = qlen == 1

    # ------------------------------------------------------------ 单块 prefill 快路
    # 只有"可见块就是自己这一个块"时（P 首填），块内 delta 全为 0，
    # 位置就是真实位置，等价于普通因果自注意力 —— 直接交给 SDPA/flash，
    # 显存从 O(qlen × 容量) 降到 O(qlen)。
    if qlen > 1 and ctx.fast_prefill and attention_mask is None:
        visible = [b for b, _ in block_slices(layout, view) if layout.lengths[b] > 0]
        if len(visible) == 1 and visible[0] is ctx.own_block:
            own = ctx.own_block
            start = layout.phys_start(own)
            n = int(layout.lengths[own])
            if n == qlen:
                k_fast = key[..., start:start + n, :]
                v_fast = value[..., start:start + n, :]
                out = torch.nn.functional.scaled_dot_product_attention(
                    query, k_fast, v_fast, dropout_p=0.0, is_causal=True,
                    scale=scaling)
                return out.transpose(1, 2).contiguous(), None

    # ------------------------------------------------------------ 批处理分支
    # 两行分别是 thinker 与 writer，视图顺序不同（P,T,W / P,W,T），
    # 所以不能共用"按视图拼接"的张量；这里对接 union_tensors 给的物理顺序并集，
    # 每行各自挑块、各自旋转 query。
    # 统一走"按行取块"的路径：单行时 rows = [(当前视图, 自己的块)]。
    # cache.update 现在返回的是**固定容量的物理缓冲**（零拷贝），
    # 所以必须用 physical_slices 取块，而不是视图拼接偏移。
    rows = getattr(ctx, "rows", None) or [(view, ctx.own_block)]
    if rows:
        from meowllm.engine.dualstream.blocks import physical_slices

        phys = physical_slices(layout)
        outs: list[torch.Tensor] = []
        for r, (view_r, own_r) in enumerate(rows):
            q_r = query[r:r + 1]
            if qlen == 1 and ctx.fast_prefill:
                s_parts: list[torch.Tensor] = []
                v_parts: list[torch.Tensor] = []
                for block, _ in block_slices(layout, view_r):
                    n_valid = int(layout.lengths[block])
                    if n_valid <= 0:
                        continue
                    b0 = layout.phys_start(block)
                    q_rot = ctx.rotator.rotate(q_r, layout.delta(own_r, block, view_r))
                    s_parts.append(torch.matmul(
                        q_rot, key[..., b0:b0 + n_valid, :].transpose(2, 3)) * scaling)
                    v_parts.append(value[..., b0:b0 + n_valid, :])
                if not s_parts:
                    raise RuntimeError(f"第 {r} 行看不到任何 K 块")
                scores_d = (s_parts[0] if len(s_parts) == 1
                            else torch.cat(s_parts, dim=-1))
                probs_d = torch.softmax(scores_d, dim=-1, dtype=torch.float32).to(q_r.dtype)
                out_d = None
                off_d = 0
                for v_block in v_parts:
                    width = v_block.shape[2]
                    part = torch.matmul(probs_d[..., off_d:off_d + width], v_block)
                    out_d = part if out_d is None else out_d + part
                    off_d += width
                outs.append(out_d)
                continue
            score_parts: list[torch.Tensor] = []
            value_parts: list[torch.Tensor] = []
            keep_parts: list[torch.Tensor] = []
            logical_parts: list[torch.Tensor] = []
            for block, _ in block_slices(layout, view_r):
                # 用**固定容量**切片（不是按当前长度），这样 kernel 参数与长度无关，
                # CUDA Graph 才能跨步复用；超出当前长度的位置靠下面的掩码屏蔽。
                cap_start = layout.phys_start(block)
                cap_width = int(layout.capacity.get(block, 0))
                if cap_width <= 0:
                    continue
                ps = slice(cap_start, cap_start + cap_width)
                delta = layout.delta(own_r, block, view_r)
                q_rot = ctx.rotator.rotate(q_r, delta)
                score_parts.append(
                    torch.matmul(q_rot, key[..., ps, :].transpose(2, 3)) * scaling)
                value_parts.append(value[..., ps, :])
                keep = torch.zeros(cap_width, dtype=torch.bool, device=key.device)
                keep[: int(layout.lengths[block])] = True
                keep_parts.append(keep)
                # 每个容量槽在"视图逻辑序列"里的位置（padding 槽钳到末尾）
                n_valid = int(layout.lengths[block])
                slot = torch.arange(cap_width, device=key.device)
                logical_parts.append(
                    slot.clamp_(max=max(n_valid - 1, 0)) + layout.start(block, view_r))
            if not score_parts:
                raise RuntimeError(f"批处理第 {r} 行看不到任何 K 块")
            scores = (score_parts[0] if len(score_parts) == 1
                      else torch.cat(score_parts, dim=-1))
            # 屏蔽 padding：容量切片里超出当前长度的位置必须置 -inf，
            # 否则它们的分数是 0，softmax 会给它们权重、稀释真实注意力
            # （这会是**静默**错误：不报异常，只是输出变垃圾）。
            keep = (keep_parts[0] if len(keep_parts) == 1
                    else torch.cat(keep_parts, dim=-1))
            scores = scores.masked_fill(~keep, torch.finfo(scores.dtype).min)
            # prefill（qlen > 1）需要因果掩码。现在切片是"按容量"，中间夹着 padding，
            # 不能再用 tril(diagonal=klen-qlen) —— 必须按**逻辑位置**比较。
            if qlen > 1:
                logical = (logical_parts[0] if len(logical_parts) == 1
                           else torch.cat(logical_parts, dim=-1))
                q_off = (layout.start(own_r, view_r)
                         + int(layout.lengths[own_r]) - qlen)
                qpos = torch.arange(q_off, q_off + qlen, device=logical.device)
                causal = logical[None, :] <= qpos[:, None]
                scores = scores.masked_fill(~causal, torch.finfo(scores.dtype).min)
            probs = torch.softmax(scores, dim=-1, dtype=torch.float32).to(q_r.dtype)
            out = None
            offset = 0
            for v_block in value_parts:
                width = v_block.shape[2]
                part = torch.matmul(probs[..., offset:offset + width], v_block)
                out = part if out is None else out + part
                offset += width
            outs.append(out)
        merged = outs[0] if len(outs) == 1 else torch.cat(outs, dim=0)
        return merged.transpose(1, 2).contiguous(), None

    # 为什么旋转 **query** 而不是 key：
    #   decode 时 query 只有 1 个 token，而每个块的 key 有几十到上百个。
    #   实测把旋转搬到 key 上会让每步从 0.16s 退到 0.36s（慢一倍多）。
    #   所以保持"逐块旋转 query + 手工加权求和"的形态。
    score_parts: list[torch.Tensor] = []
    value_parts: list[torch.Tensor] = []
    for block, sl in block_slices(layout, view):
        if sl.stop <= sl.start:
            continue                      # 空块 / 该视图不可见的块
        delta = layout.delta(ctx.own_block, block, view)
        q_rot = ctx.rotator.rotate(query, delta)
        score_parts.append(torch.matmul(q_rot, key[..., sl, :].transpose(2, 3)) * scaling)
        value_parts.append(value[..., sl, :])

    if not score_parts:
        raise RuntimeError("attention 看不到任何 K 块，BlockCache 可能未初始化")

    scores = score_parts[0] if len(score_parts) == 1 else torch.cat(score_parts, dim=-1)

    if not is_decode:
        # prefill 时块内多点前向需要因果掩码：物理拼接顺序 == 视图逻辑顺序，
        # 所以用 tril 即可。模型通常给 None（把因果交给内核标志），必须自己补。
        klen = scores.shape[-1]
        causal = torch.tril(
            torch.ones(qlen, klen, dtype=torch.bool, device=scores.device),
            diagonal=klen - qlen)
        scores = scores.masked_fill(~causal, torch.finfo(scores.dtype).min)
        if attention_mask is not None:
            if attention_mask.dtype == torch.bool:
                mask = attention_mask.squeeze(1) if attention_mask.dim() == 4 else attention_mask
                scores = scores.masked_fill(~mask, torch.finfo(scores.dtype).min)
            else:
                scores = scores + attention_mask

    probs = torch.softmax(scores, dim=-1, dtype=torch.float32).to(query.dtype)
    if dropout and module.training:
        probs = torch.nn.functional.dropout(probs, p=dropout)

    out = None
    offset = 0
    for v_block in value_parts:
        width = v_block.shape[2]
        part = torch.matmul(probs[..., offset:offset + width], v_block)
        out = part if out is None else out + part
        offset += width

    # ⚠ 必须是 (B, L, H, D)：调用方随后 reshape(*input_shape, -1)。
    return out.transpose(1, 2).contiguous(), None


def attach(model, ctx: ARContext) -> int:
    """把 ctx 挂到模型里所有 attention 模块上，返回挂载数量。

    同时注册自定义实现并让模型改用��� —— 顺序不能反（见 compat.set_attn_impl）。
    """
    from meowllm.engine.dualstream.compat import set_attn_impl

    register_attention(ATTN_NAME, ar_attention_forward)
    count = 0
    for m in model.modules():
        # Qwen3Attention 有 layer_idx 与 o_proj；用这个组合识别，避免误伤其它模块
        if hasattr(m, "layer_idx") and hasattr(m, "o_proj"):
            m._meowllm_ctx = ctx          # noqa: SLF001 - 我们自己的上下文
            count += 1
    if count == 0:
        raise RuntimeError("没找到任何 attention 模块，模型结构与预期不符")
    set_attn_impl(model)
    return count
