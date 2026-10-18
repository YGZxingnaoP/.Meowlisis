# -*- coding: utf-8 -*-
"""δ-mem：给冻结 backbone 挂一个在线联想记忆状态（Delta Memory）。

论文：*δ-mem: Efficient Online Memory for Large Language Models*
（`.vendor/.MeowLLM/docs/EfficientOnlineMemoryforLarge.pdf`）

一句话：把历史压进一个 r×r 的状态矩阵 `S`，用 delta 规则（带逐维遗忘门）在线更新；
生成时用当前隐状态去查 `S` 得到读向量 `r_t`，再用两个低秩映射把 `r_t` 变成
**query 侧修正**与**输出侧修正**，直接参与 attention 计算 —— backbone 全程冻结。

本包与论文的对应关系
--------------------
    δ-mem 公式 (4)   记忆投影 q^m/k^m/v^m/β        -> layer.DeltaMemLayer.memory_vectors
    δ-mem 公式 (6)   读 rt = S_{t-1} q^m           -> layer.DeltaMemLayer.read
    δ-mem 公式 (7-9) Δq/Δo + α 注入 attention      -> inject.py
    δ-mem 公式 (10)  gated delta 写入              -> layer.DeltaMemLayer.pool_chunks
                                                    + memory.DeltaMem.write_state
    §3.5 写入粒度     TSW / SSW / MSW              -> cfg.chunk / cfg.n_states
    §3.6 训练目标     只对 response 算 CE，context 不重放 -> train/sft.py

刻意做的工程取舍（与论文不同，都有理由，见各文件顶部注释）
----------------------------------------------------------
1. 写入阶段关闭 steering（α=0）：backbone 单趟前向采 hidden，再离线跑 chunk 递推。
2. 写入粒度用 chunk 化的 SSW（chunk 可配，1 = TSW）；MSW 用分组投影实现。
3. 生成期间状态冻结（只在"写记忆"那一步更新）。
4. Δq 借 RoPE 的线性性在 attention 接口处注入，等价于论文的"pre-RoPE 相加"。
5. α 可学习，按初始化比例定标（论文固定 α=16）。
"""

from meowllm.dmem.config import DeltaMemConfig
from meowllm.dmem.layer import DeltaMemLayer
from meowllm.dmem.memory import DeltaMem

__all__ = ["DeltaMemConfig", "DeltaMemLayer", "DeltaMem"]
