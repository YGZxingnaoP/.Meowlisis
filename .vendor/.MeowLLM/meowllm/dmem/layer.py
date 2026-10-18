# -*- coding: utf-8 -*-
"""δ-mem 的单层参数与状态运算（论文公式 4/6/7/10）。

一层只持有一组小矩阵：

    w_q / w_k / w_v / w_beta : d -> N*r       记忆投影（公式 4、5）
    w_dq / w_do              : N*r -> q_dim   低秩修正（公式 7）
    log_alpha                : 标量            §3.3 的 α

注意 q_dim ≠ d：Qwen3-0.6B 是 q_dim=16*128=2048、d=1024，别混。

状态布局
--------
`S` 形状 (B, N, r, r)，fp32。论文的 `S ∈ R^{r×r}`，MSW 的 N 个并行子状态
就是这里的 N 维。逐维门 β/λ 作用在 S 的**行**上（对应公式 12）：
`s_t^(i) = λ_i s_{t-1}^(i) + β_i (v_i - s_{t-1}^(i)·k) k^T`。
"""

from __future__ import annotations

import math

import torch
from torch import nn

from meowllm.dmem.config import DeltaMemConfig


def l2norm(x: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    """按最后一维做 L2 归一化（公式 4 里的 norm）。"""
    return x / x.norm(dim=-1, keepdim=True).clamp_min(eps)


def rotate_half(x: torch.Tensor) -> torch.Tensor:
    """RoPE 的半维交换：[-x2, x1]。与 transformers 的 apply_rotary_pos_emb 同构。"""
    half = x.shape[-1] // 2
    x1, x2 = x[..., :half], x[..., half:]
    return torch.cat((-x2, x1), dim=-1)


def apply_rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    """把已按 (B,H,L,D) 排好的张量旋转。cos/sin 允许 (B,L,D) 或 (B,1,L,D)。"""
    if cos.dim() == 3:
        cos = cos.unsqueeze(1)
        sin = sin.unsqueeze(1)
    return x * cos + rotate_half(x) * sin


class DeltaMemLayer(nn.Module):
    """一层的 δ-mem。参数全部 fp32（量小、稳），与 backbone 的 bf16 混用。"""

    def __init__(self, hidden_size: int, q_dim: int, cfg: DeltaMemConfig,
                 layer_idx: int) -> None:
        super().__init__()
        self.cfg = cfg
        self.layer_idx = int(layer_idx)
        self.hidden_size = int(hidden_size)
        self.q_dim = int(q_dim)
        self.n = max(1, int(cfg.n_states))
        self.r = int(cfg.rank)
        self.dim = self.n * self.r           # 投影输出维度
        self.chunk = max(1, int(cfg.chunk))

        self.w_q = nn.Linear(self.hidden_size, self.dim, bias=False, dtype=torch.float32)
        self.w_k = nn.Linear(self.hidden_size, self.dim, bias=False, dtype=torch.float32)
        self.w_v = nn.Linear(self.hidden_size, self.dim, bias=False, dtype=torch.float32)
        self.w_beta = nn.Linear(self.hidden_size, self.dim, bias=True, dtype=torch.float32)
        self.w_dq = nn.Linear(self.dim, self.q_dim, bias=False, dtype=torch.float32)
        self.w_do = nn.Linear(self.dim, self.q_dim, bias=False, dtype=torch.float32)
        if cfg.learn_alpha:
            self.log_alpha = nn.Parameter(
                torch.tensor(math.log(max(float(cfg.alpha), 1e-6)), dtype=torch.float32))
        else:
            self.register_buffer("log_alpha", torch.tensor(
                math.log(max(float(cfg.alpha), 1e-6)), dtype=torch.float32))
        self.reset_parameters()

    # ------------------------------------------------------------------ 初始化
    def reset_parameters(self) -> None:
        """投影用 1/sqrt(d) 的 normal：输入是 RMSNorm 后的量（每元素 rms≈1），
        这样 tanh 前激活的量级就是 1，l2norm 后的方向有区分度。

        w_dq / w_do 用很小的 std：让初始修正 ≈ init_ratio × |q|。
        在 |rt| ≈ sqrt(N*r)、|q| ≈ sqrt(q_dim) 的估计下，α·|Δq|/|q| ≈ α·std·sqrt(N*r)。
        """
        std = 1.0 / math.sqrt(max(self.hidden_size, 1))
        for w in (self.w_q, self.w_k, self.w_v):
            nn.init.normal_(w.weight, mean=0.0, std=std)
        nn.init.normal_(self.w_beta.weight, mean=0.0, std=std)
        nn.init.constant_(self.w_beta.bias, float(self.cfg.beta_bias))
        alpha = float(torch.exp(self.log_alpha).item())
        d_std = float(self.cfg.init_ratio) / max(alpha * math.sqrt(self.dim), 1e-6)
        nn.init.normal_(self.w_dq.weight, mean=0.0, std=d_std)
        nn.init.normal_(self.w_do.weight, mean=0.0, std=d_std)

    @property
    def alpha(self) -> torch.Tensor:
        return torch.exp(self.log_alpha)

    # -------------------------------------------------------------- 记忆投影
    def memory_vectors(self, x: torch.Tensor):
        """公式 4/5：把隐状态投到记忆空间。

        x: (..., d) 任意前导维 -> qm/km/vm: (..., N, r)，beta: (..., N, r)
        """
        x = x.to(torch.float32)
        shape = (*x.shape[:-1], self.n, self.r)
        qm = l2norm(torch.tanh(self.w_q(x)).view(shape))
        km = l2norm(torch.tanh(self.w_k(x)).view(shape))
        vm = self.w_v(x).view(shape)
        beta = torch.sigmoid(self.w_beta(x)).view(shape)
        return qm, km, vm, beta

    def query_vector(self, x: torch.Tensor) -> torch.Tensor:
        """只要 qm 时的轻量路径（生成阶段每步都调，省掉 k/v/β 的三次投影）。"""
        x = x.to(torch.float32)
        shape = (*x.shape[:-1], self.n, self.r)
        return l2norm(torch.tanh(self.w_q(x)).view(shape))

    # ------------------------------------------------------------------ 读
    @staticmethod
    def read(state: torch.Tensor, qm: torch.Tensor) -> torch.Tensor:
        """公式 6：rt = S qm。

        state: (B, N, r, r)；qm: (B, L, N, r) -> rt: (B, L, N, r)
        右乘 qm 等价于论文的 `S @ q`（S 按 [i, j] 存，rt_i = Σ_j S_ij q_j）。
        """
        return torch.einsum("bnrs,blns->blnr", state, qm)

    def steer(self, rt: torch.Tensor):
        """公式 7：Δq = α W_q^Δ rt，Δo = α W_o^Δ rt。

        rt: (B, L, N*r) -> Δq/Δo: (B, L, q_dim)
        Δo 不参与 RoPE（它加在 attention 之后），Δq 由调用方按位置旋转。
        """
        flat = rt.reshape(*rt.shape[:-2], self.dim)
        alpha = self.alpha.to(flat.dtype)
        return self.w_dq(flat) * alpha, self.w_do(flat) * alpha

    # ------------------------------------------------------------------ 写
    def pool_chunks(self, km, vm, beta, boundaries=None):
        """把逐 token 的写向量按 chunk 平均（公式 14 的段表示）。

        km/vm/beta: (B, L, N, r)
        boundaries: 可选的段长列表（真实消息边界）；None 则按 cfg.chunk 均分。
        返回 (B, C, N, r) 的三元组。
        """
        b, length = km.shape[0], km.shape[1]
        if boundaries:
            chunks = []
            start = 0
            for size in list(boundaries):
                size = int(size)
                if size <= 0:
                    continue
                end = min(start + size, length)
                if end > start:
                    chunks.append((start, end))
                start = end
            if start < length:
                chunks.append((start, length))
        else:
            size = self.chunk
            chunks = [(i, min(i + size, length)) for i in range(0, length, size)]
        if not chunks:
            zero = km.new_zeros((b, 0, self.n, self.r))
            return zero, zero, zero
        ks, vs, bs = [], [], []
        for start, end in chunks:
            ks.append(km[:, start:end].mean(dim=1))
            vs.append(vm[:, start:end].mean(dim=1))
            bs.append(beta[:, start:end].mean(dim=1))
        return (torch.stack(ks, dim=1), torch.stack(vs, dim=1),
                torch.stack(bs, dim=1))
