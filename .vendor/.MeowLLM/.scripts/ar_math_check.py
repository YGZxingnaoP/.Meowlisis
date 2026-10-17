# -*- coding: utf-8 -*-
"""数学验证：我的 block attention 是否与 sdpa 在同一输入上等价。

为什么要单独做这一层
--------------------
之前用"整模型 logits 的余弦"当指标，分辨率太差：
logits 有巨大的均值与尺度，即使隐藏状态已经偏了，余弦仍可能显示 0.999。
本脚本把 attention 单独拎出来，和 PyTorch 的 `scaled_dot_product_attention`
在**完全相同的输入**上对比，误差是什么量级一目了然。

论文公式（§3.3）：
    A := [ ρ(q, iq − i_P)·K_P , ρ(q, iq − i_T)·K_T , ρ(q, iq − i_W)·K_W ]
其中 K 按**块内相对位置**存储（脚注 4），q 按"视图内位置"旋转。

三个用例
--------
A. 单块 prefill（L == S，因果）
B. 单块 decode（L == 1，全可见）
C. 三块 + delta，对照"物理重排后的 sdpa"
"""

from __future__ import annotations

import sys
from pathlib import Path

import torch
import torch.nn.functional as F

MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from meowllm.engine.dualstream.attention import ARContext, ar_attention_forward  # noqa: E402
from meowllm.engine.dualstream.blocks import Block, BlockLayout, View  # noqa: E402

D_HEAD = 8
H_Q = 4
H_KV = 2
N_REP = H_Q // H_KV
THETA = 10000.0


class Rotary:
    def __init__(self) -> None:
        half = D_HEAD // 2
        self.inv_freq = 1.0 / (THETA ** (torch.arange(0, half).float() / half))

    def __call__(self, x, position_ids):
        pos = position_ids.float().reshape(-1, 1)
        freqs = pos * self.inv_freq.reshape(1, -1)
        emb = torch.cat([freqs, freqs], dim=-1)
        return emb.cos(), emb.sin()


def rot(x, positions, rotary):
    pos = torch.tensor([positions], dtype=torch.long)
    cos, sin = rotary(x, pos)
    cos = cos.unsqueeze(0).unsqueeze(0)
    sin = sin.unsqueeze(0).unsqueeze(0)
    half = x.shape[-1] // 2
    return x * cos + torch.cat([-x[..., half:], x[..., :half]], dim=-1) * sin


class Rotator:
    def __init__(self, rotary):
        self.rotary = rotary

    def rotate(self, q, delta):
        return q if delta == 0 else rot(q, [int(delta)], self.rotary)


class Mod:
    def __init__(self, ctx):
        self.num_key_value_groups = N_REP
        self.scaling = D_HEAD ** -0.5
        self.training = False
        self._meowllm_ctx = ctx


def report(tag: str, mine: torch.Tensor, ref: torch.Tensor) -> bool:
    delta = (mine - ref).abs().max().item()
    scale = ref.abs().max().item()
    rel = delta / max(scale, 1e-9)
    ok = rel < 1e-4
    print(f"  {'OK  ' if ok else 'BAD '}{tag:<34} max|Δ|={delta:.3e}  "
          f"相对={rel:.3e}  (参考量级 {scale:.2f})")
    return ok


def main() -> int:
    torch.manual_seed(3)
    rotary = Rotary()
    rotator = Rotator(rotary)
    ok_all = True

    # ---------------- A. 单块 prefill ----------------
    L = 6
    q = torch.randn(1, H_Q, L, D_HEAD)
    k = torch.randn(1, H_KV, L, D_HEAD)
    v = torch.randn(1, H_KV, L, D_HEAD)
    layout = BlockLayout()
    layout.set_len(Block.PROMPT_W, L)
    ctx = ARContext(layout=layout, rotator=rotator,
                    view=View.WRITER, own_block=Block.PROMPT_W)
    mine, _ = ar_attention_forward(Mod(ctx), q, k, v, None)
    ref = F.scaled_dot_product_attention(
        q, k.repeat_interleave(N_REP, dim=1), v.repeat_interleave(N_REP, dim=1),
        is_causal=True, scale=D_HEAD ** -0.5)
    print("\nA. 单块 prefill（L=6，因果）")
    ok_all &= report("我的实现 vs sdpa", mine, ref.transpose(1, 2))

    # ---------------- B. 单块 decode ----------------
    q1 = torch.randn(1, H_Q, 1, D_HEAD)
    layout2 = BlockLayout()
    layout2.set_len(Block.PROMPT_W, 5)
    layout2.set_len(Block.WRITER, 1)
    ctx2 = ARContext(layout=layout2, rotator=rotator,
                     view=View.WRITER, own_block=Block.WRITER)
    k2 = torch.randn(1, H_KV, 6, D_HEAD)
    v2 = torch.randn(1, H_KV, 6, D_HEAD)
    mine2, _ = ar_attention_forward(Mod(ctx2), q1, k2, v2, None)
    # 参考实现里 query 必须旋到它的"视图内逻辑位置"：p+t+w-1 = 5+0+1-1 = 5。
    # 我这一版实现收到的 q 是"块内位置"（w-1 = 0，即未旋转），
    # 差值 delta = start(W)-start(P) = 5 由实现内部补上 —— 所以参考侧要显式旋 5。
    ref_q2 = rot(q1, [5], rotary)
    ref2 = F.scaled_dot_product_attention(
        ref_q2, k2.repeat_interleave(N_REP, dim=1), v2.repeat_interleave(N_REP, dim=1),
        is_causal=False, scale=D_HEAD ** -0.5)
    print("\nB. 单块 decode（L=1，全可见）")
    ok_all &= report("我的实现 vs sdpa", mine2, ref2.transpose(1, 2))

    # ---------------- C. 三块 + delta ----------------
    p, t, w = 4, 3, 3
    layout3 = BlockLayout()
    layout3.set_len(Block.PROMPT_W, p)
    layout3.set_len(Block.THINKER, t)
    layout3.set_len(Block.WRITER, w)
    # 原始（未旋转）K/V 与 query
    kP = torch.randn(1, H_KV, p, D_HEAD)
    kT = torch.randn(1, H_KV, t, D_HEAD)
    kW = torch.randn(1, H_KV, w, D_HEAD)
    vP, vT, vW = (torch.randn(1, H_KV, n, D_HEAD) for n in (p, t, w))
    q_raw = torch.randn(1, H_Q, 1, D_HEAD)

    # 存储形态：键按块内相对位置旋转
    sP = rot(kP, list(range(p)), rotary)
    sT = rot(kT, list(range(t)), rotary)
    sW = rot(kW, list(range(w)), rotary)
    # 查询：模型会给它按"块内位置"旋转，这里 w-1
    q_stored = rot(q_raw, [w - 1], rotary)

    ctx3 = ARContext(layout=layout3, rotator=rotator,
                     view=View.WRITER, own_block=Block.WRITER)
    mine3, _ = ar_attention_forward(
        Mod(ctx3), q_stored,
        torch.cat([sP, sT, sW], dim=2),
        torch.cat([vP, vT, vW], dim=2), None)

    # 参考：物理重排（P→T→W），连续位置
    ref_k = rot(torch.cat([kP, kT, kW], dim=2), list(range(p + t + w)), rotary)
    ref_q = rot(q_raw, [p + t + w - 1], rotary)
    ref3 = F.scaled_dot_product_attention(
        ref_q, ref_k.repeat_interleave(N_REP, dim=1),
        torch.cat([vP, vT, vW], dim=2).repeat_interleave(N_REP, dim=1),
        is_causal=False, scale=D_HEAD ** -0.5)
    print("\nC. 三块 + delta vs 物理重排")
    ok_all &= report("我的实现 vs 物理重排", mine3, ref3.transpose(1, 2))

    print("\n结论：")
    print("  A/B 有一个 BAD -> attention 实现本身与 sdpa 不一致（实现 bug）")
    print("  A/B 都 OK、C BAD -> 块 delta 或块顺序有问题（数学 bug）")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
