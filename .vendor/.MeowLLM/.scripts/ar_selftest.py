# -*- coding: utf-8 -*-
"""AsyncReasoning 核心数学自检（**不需要模型权重**）。

验什么
------
1. 块布局的 delta 角度表，与"直接算视图内逻辑位置差"的暴力结果一致
2. 自定义 attention 的输出，与"把 token 真的按视图顺序拼成连续序列"的结果一致
   —— 这就是论文 P2 的对拍，只是把"模型"换成了随机张量 + 假 RoPE，
      所以**没有权重也能先验一遍数学**

用法（在 .vendor/.MeowLLM 目录下）
---------------------------------
    ..\\..\\runtime\\311\\python.exe .scripts\\ar_selftest.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import torch

# 让 `import meowllm` 能工作（脚本在 <模块根>/.scripts/ 下）
MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT))
os.environ.setdefault("PYTHONUTF8", "1")

from meowllm.engine.dualstream.attention import ARContext, ar_attention_forward  # noqa: E402
from meowllm.engine.dualstream.blocks import (  # noqa: E402
    Block, BlockCache, BlockLayout, View, block_slices,
)

HEAD_DIM = 8
N_Q_HEADS = 2
N_KV_HEADS = 1
ROPE_THETA = 10000.0


class FakeRotary:
    """复刻 Qwen3 的 rotary 约定：freqs = pos * inv_freq，emb = cat(freqs, freqs)。"""

    def __init__(self) -> None:
        half = HEAD_DIM // 2
        self.inv_freq = 1.0 / (ROPE_THETA ** (torch.arange(0, half).float() / half))

    def __call__(self, x, position_ids):
        pos = position_ids.float().reshape(-1, 1)          # (T, 1)
        freqs = pos * self.inv_freq.reshape(1, -1)          # (T, half)
        emb = torch.cat([freqs, freqs], dim=-1)             # (T, dim)
        return emb.cos(), emb.sin()


def rotate(x: torch.Tensor, positions: list[int], rotary: FakeRotary) -> torch.Tensor:
    """按给定位置旋转张量 (B, H, T, D)。"""
    pos = torch.tensor([positions], dtype=torch.long)
    cos, sin = rotary(x, pos)
    cos = cos.unsqueeze(0).unsqueeze(0)      # (1,1,T,D)
    sin = sin.unsqueeze(0).unsqueeze(0)
    half = x.shape[-1] // 2
    rot_half = torch.cat([-x[..., half:], x[..., :half]], dim=-1)
    return x * cos + rot_half * sin


class FakeRotator:
    """DeltaRotator 的替身：因为没有真模型的 rotary_emb。"""

    def __init__(self, rotary: FakeRotary) -> None:
        self.rotary = rotary

    def rotate(self, q: torch.Tensor, delta: int) -> torch.Tensor:
        if delta == 0:
            return q
        return rotate(q, [int(delta)], self.rotary)


class FakeAttnModule:
    """模拟 Qwen3Attention 里我们用到的那几个属性。"""

    def __init__(self, ctx: ARContext) -> None:
        self.num_key_value_groups = N_Q_HEADS // N_KV_HEADS
        self.scaling = HEAD_DIM ** -0.5
        self.training = False
        self._meowllm_ctx = ctx


def check_layout_delta() -> bool:
    """delta 表 vs 暴力位置差。"""
    ok = True
    for p, t, w in ((5, 3, 4), (1, 1, 1), (10, 7, 2), (3, 0, 9)):
        layout = BlockLayout()
        layout.set_len(Block.PROMPT, p)
        layout.set_len(Block.THINKER, t)
        layout.set_len(Block.WRITER, w)
        for view in (View.WRITER, View.THINKER):
            for qb in layout.order(view):
                for kb in layout.order(view):
                    got = layout.delta(qb, kb, view)
                    # 暴力算法：视图内逻辑起点之差
                    want = layout.start(qb, view) - layout.start(kb, view)
                    # 再独立验一次：任意一对 token 的相对距离要等于逻辑距离
                    q_store, k_store = 0, 0
                    if q_store + got - k_store != want:
                        ok = False
                    if got != want:
                        print(f"  [FAIL] p={p} t={t} w={w} {view} "
                              f"q={qb} k={kb}: got={got} want={want}")
                        ok = False
    print(("[PASS] " if ok else "[FAIL] ") + "块布局 delta 表")
    return ok


def check_attention_equivalence() -> bool:
    """自定义 attention vs 物理重排参考实现（随机张量）。"""
    p, t, w = 6, 5, 4
    layout = BlockLayout()
    layout.set_len(Block.PROMPT, p)
    layout.set_len(Block.THINKER, t)
    layout.set_len(Block.WRITER, w)

    torch.manual_seed(7)
    rotary = FakeRotary()
    rotator = FakeRotator(rotary)

    # 三个块的原始（未旋转）K/V，按块存放
    raw = {b: (torch.randn(1, N_KV_HEADS, n, HEAD_DIM),
               torch.randn(1, N_KV_HEADS, n, HEAD_DIM))
           for b, n in ((Block.PROMPT, p), (Block.THINKER, t), (Block.WRITER, w))}

    # 存储形式：键按"块内相对位置"旋转
    stored = {}
    for b, (k, v) in raw.items():
        stored[b] = (rotate(k, list(range(k.shape[2])), rotary), v)

    query_raw = torch.randn(1, N_Q_HEADS, 1, HEAD_DIM)

    ok = True
    for view in (View.WRITER, View.THINKER):
        # ---- 我们的实现：单 query 落在视图最后一个块上 ----
        own = layout.order(view)[-1]
        # 进入 attention 前，query 已按 **块内相对位置** 被 RoPE 旋过
        q_stored = rotate(query_raw, [layout.lengths[own] - 1], rotary)

        ctx = ARContext(layout=layout, rotator=rotator, view=view, own_block=own)
        module = FakeAttnModule(ctx)
        key = torch.cat([stored[b][0] for b in layout.order(view)], dim=2)
        value = torch.cat([stored[b][1] for b in layout.order(view)], dim=2)
        got, _ = ar_attention_forward(module, q_stored, key, value, None)

        # ---- 参考实现：真按视图顺序拼成连续序列，位置 0..n-1 ----
        total = layout.total()
        ref_ids = layout.order(view)
        ref_key = torch.cat([raw[b][0] for b in ref_ids], dim=2)
        ref_val = torch.cat([raw[b][1] for b in ref_ids], dim=2)
        ref_key = rotate(ref_key, list(range(total)), rotary)
        ref_q = rotate(query_raw, [total - 1], rotary)
        ref_k = ref_key.repeat_interleave(module.num_key_value_groups, dim=1)
        ref_v = ref_val.repeat_interleave(module.num_key_value_groups, dim=1)
        score = torch.matmul(ref_q, ref_k.transpose(2, 3)) * module.scaling
        prob = torch.softmax(score.float(), dim=-1).to(ref_q.dtype)
        want = torch.matmul(prob, ref_v)

        delta = (got - want).abs().max().item()
        passed = delta < 1e-5
        ok = ok and passed
        print(f"  {'[PASS]' if passed else '[FAIL]'} {view.value:<8} "
              f"max|Δ| = {delta:.3e}  形状 {tuple(got.shape)}")

    print(("[PASS] " if ok else "[FAIL] ") + "attention 与物理重排等价")
    return ok


def check_cache_roundtrip() -> bool:
    """BlockCache：追加 → 视图拼接 → 截断。"""
    layout = BlockLayout()
    cache = BlockCache(layout, view=View.WRITER, target_block=Block.PROMPT)

    layout.set_len(Block.PROMPT, 3)
    cache.update(torch.randn(1, N_KV_HEADS, 3, HEAD_DIM),
                 torch.randn(1, N_KV_HEADS, 3, HEAD_DIM), 0)
    layout.set_len(Block.WRITER, 2)
    cache.view, cache.target_block = View.WRITER, Block.WRITER
    cache.update(torch.randn(1, N_KV_HEADS, 2, HEAD_DIM),
                 torch.randn(1, N_KV_HEADS, 2, HEAD_DIM), 0)

    k_writer, _ = cache.view_tensors(0)
    cache.view = View.THINKER
    k_thinker, _ = cache.view_tensors(0)

    ok = True
    if k_writer.shape[2] != 5:
        print(f"  [FAIL] writer 视图长度 {k_writer.shape[2]} != 5")
        ok = False
    if not torch.allclose(k_writer[..., :3, :], k_thinker[..., :3, :]):
        print("  [FAIL] 两视图的 P 块内容不一致")
        ok = False

    # 截断：把 WRITER 块截到 0，视图里就只剩 P
    cache.truncate(Block.WRITER, 0)
    layout.set_len(Block.WRITER, 0)
    cache.view = View.WRITER
    k_after, _ = cache.view_tensors(0)
    if k_after.shape[2] != 3:
        print(f"  [FAIL] 截断后长度 {k_after.shape[2]} != 3")
        ok = False

    print(("[PASS] " if ok else "[FAIL] ") + "BlockCache 追加/视图/截断")
    return ok


def main() -> int:
    print("=" * 62)
    print("AsyncReasoning 核心数学自检（无需权重）")
    print("=" * 62)

    from meowllm.engine.dualstream import compat

    problems = compat.self_check()
    if problems:
        print("[WARN] 环境自检有提示：")
        for item in problems:
            print("   -", item)
    else:
        print("[PASS] transformers 插槽自检")

    print("")
    results = [
        check_layout_delta(),
        check_attention_equivalence(),
        check_cache_roundtrip(),
    ]
    print("")
    print("=" * 62)
    if all(results):
        print("全部通过")
        return 0
    print("有失败项，先修数学再接模型")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
