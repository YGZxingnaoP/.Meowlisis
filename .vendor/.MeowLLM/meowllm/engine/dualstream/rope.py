# -*- coding: utf-8 -*-
"""把 delta 角度施加到 query 上。

为什么需要"补一次旋转"
----------------------
transformers 的 Qwen3 在进入 attention 之前就调用了
`apply_rotary_pos_emb(query, key, cos, sin)`，此时 query 与 key 都按
`position_ids` 给了同一个角度。而我们要的是"同一个键在不同视图里被看到
不同距离"，所以只能对 **query** 再补一个差值角度。

旋转是可叠加的：ρ(q, a) 之后再旋 b，等价于 ρ(q, a+b)。
所以只要拿到 delta 的正确 cos/sin 即可，不需要知道绝对位置。

cos/sin 从哪来
--------------
不自算：直接调模型自己的 `rotary_emb`，保证与 transformers 的旋转基、
rope_scaling（如 YaRN）、dtype 完全一致。任何自算实现都迟早会和它错位。
"""

from __future__ import annotations

import torch


def rotate_half(x: torch.Tensor) -> torch.Tensor:
    """transformers 的 half-rotation 约定（非 interleaved）。

    等价于把后半段取负移到前面：[-x[..., half:], x[..., :half]]
    """
    half = x.shape[-1] // 2
    return torch.cat([-x[..., half:], x[..., :half]], dim=-1)


class DeltaRotator:
    """按 delta 缓存 cos/sin，并对 query 施加增量旋转。

    一个模型实例一个 rotator；delta 取值很有限（就是块起点的几个差值），
    所以缓存命中率接近 100%。
    """

    def __init__(self, model) -> None:
        #: 模型自身的 rotary 模块（Qwen3 在 model.model.rotary_emb）
        self._rotary = None
        for owner in (model, getattr(model, "model", None)):
            rotary = getattr(owner, "rotary_emb", None)
            if rotary is not None:
                self._rotary = rotary
                break
        if self._rotary is None:
            raise RuntimeError("找不到模型的 rotary_emb，无法计算 delta 角度")
        self._cache: dict[tuple[int, torch.device, torch.dtype],
                          tuple[torch.Tensor, torch.Tensor]] = {}

    def cos_sin(self, delta: int, ref: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """取得位置 delta 对应的 (cos, sin)，形状 (1, 1, 1, head_dim)。"""
        key = (int(delta), ref.device, ref.dtype)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        position_ids = torch.tensor([[int(delta)]], device=ref.device, dtype=torch.long)
        # rotary 的 forward 签名是 (x, position_ids)；x 只用来取 device/dtype
        cos, sin = self._rotary(ref, position_ids=position_ids)
        # 统一成 (1, 1, 1, dim) 以便与 (B, heads, 1, dim) 广播
        cos = cos.reshape(1, 1, 1, -1).to(dtype=ref.dtype, device=ref.device)
        sin = sin.reshape(1, 1, 1, -1).to(dtype=ref.dtype, device=ref.device)
        self._cache[key] = (cos, sin)
        return cos, sin

    def rotate(self, q: torch.Tensor, delta: int) -> torch.Tensor:
        """把 query 额外旋转 delta 个位置；delta=0 时原样返回（零开销）。"""
        if delta == 0:
            return q
        cos, sin = self.cos_sin(delta, q)
        return (q * cos) + (rotate_half(q) * sin)
