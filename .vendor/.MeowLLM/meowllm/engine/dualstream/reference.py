# -*- coding: utf-8 -*-
"""物理重排参考实现（对拍基准 + 降级路径）。

严格按论文 Figure 2 的布局：**每个视图有独立的 Prompt Block 和独立的 linker**。

    writer 视图:  PROMPT_W -> THINKER -> LINK_W -> WRITER
    thinker 视图: PROMPT_T -> WRITER  -> LINK_T -> THINKER

把可见块按上述顺序**真的**拼成一条连续序列，位置取 0..n-1，走一次普通前向
（标准 attention，不旋转查询、不共享块）。这与块 KV + 查询旋转数学等价，
所以用来对拍；块实现卡住时也可作为降级路径。
"""

from __future__ import annotations

import torch

from meowllm.engine.dualstream.blocks import Block, View, VIEW_ORDER


def sequence_for_view(blocks: dict[Block, list[int]], view: View
                      ) -> tuple[torch.Tensor, torch.Tensor]:
    """按视图顺序拼出连续序列，位置取 0..n-1。

    blocks: {块: token id 列表}，缺失的块按空处理。
    返回 (input_ids, position_ids)，形状都是 (1, n)。
    """
    flat: list[int] = []
    for block in VIEW_ORDER[view]:
        flat.extend(blocks.get(block) or [])
    if not flat:
        raise ValueError("序列为空：该视图所有块都没有 token")
    ids = torch.tensor([flat], dtype=torch.long)
    positions = torch.arange(len(flat), dtype=torch.long).unsqueeze(0)
    return ids, positions


def _with_impl(model, name: str):
    """临时切换 attention 实现，返回原值以便恢复。"""
    old = getattr(model.config, "_attn_implementation", None)
    model.config._attn_implementation = name  # noqa: SLF001
    return old


def next_token_logits(model, blocks: dict[Block, list[int]], view: View,
                      device: torch.device | str = "cuda") -> torch.Tensor:
    """用普通前向算出"该视图下一个 token"的 logits，形状 (vocab,)。

    临时把 attention 实现切回 "sdpa"，避免走我们的块注意力。
    """
    ids, positions = sequence_for_view(blocks, view)
    ids = ids.to(device)
    positions = positions.to(device)

    old = _with_impl(model, "sdpa")
    try:
        with torch.no_grad():
            out = model(input_ids=ids, position_ids=positions, use_cache=False)
    finally:
        if old is not None:
            model.config._attn_implementation = old  # noqa: SLF001
    return out.logits[0, -1].float()
