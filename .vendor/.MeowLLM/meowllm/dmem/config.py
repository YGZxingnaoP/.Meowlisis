# -*- coding: utf-8 -*-
"""δ-mem 超参。

字段与论文的对应（默认值 = 论文 + 0.6B 小模型的适配值）：

    rank      r，记忆空间维度。论文 r=8（配 d=2560）。0.6B 的 d=1024，
              论文比例换算过来只有 r≈3；直接放大到 64 是本项目要试的重点。
    chunk     写入粒度。1 = TSW（逐 token），16 = SSW（按 16 token 的消息段），
              论文 §3.5 三种粒度里 MSW 之外的两档就是这个参数。
    n_states  MSW 的子状态数 N（论文 N=4）。每个子状态有独立的 r×r 状态与
              独立投影，读出来 concat 成 N*r 维再走 Δq/Δo。
    alpha     §3.3 的 α，论文固定 16。这里默认按可学习标量处理。
    beta_bias 写入门 β=σ(Wx+b) 的 bias 初值。负值让训练开始时写入很轻，
              状态不至于一开始就被噪声灌满（论文未写，属工程补充）。
    window    写记忆时一次前向的 token 数。8192 token 一次算 hidden 在 8GB
              卡上会炸，所以分段前向 + KV cache 接力。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class DeltaMemConfig:
    rank: int = 64
    chunk: int = 16
    n_states: int = 1
    alpha: float = 16.0
    learn_alpha: bool = True
    #: 初始化时 |α·Δq| / |q| 的目标比例（只用于定 w_dq/w_do 的初始化 std）
    init_ratio: float = 0.08
    beta_bias: float = -2.0
    #: 空元组 = 挂到全部层（论文 §5.3 结论：全层最好）
    layers: tuple = ()
    #: 写记忆的一趟前向窗口大小（token）
    window: int = 2048
    #: 写记忆那一趟是否也打开 steering。False = 用 backbone 自己的隐状态写
    #: （论文是 True 的，但那样无法一次前向算完，代价见 inject.py 顶部注释）
    write_steering: bool = False
    #: 状态矩阵的 dtype（float32 保值；bf16 会漂）
    state_dtype: str = "float32"

    @property
    def read_dim(self) -> int:
        """读向量维度 = N*r，也就是 Δq/Δo 的输入维度。"""
        return int(self.n_states) * int(self.rank)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["layers"] = list(self.layers)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "DeltaMemConfig":
        names = set(cls.__dataclass_fields__)
        kwargs = {k: v for k, v in (data or {}).items() if k in names}
        if kwargs.get("layers") is not None:
            kwargs["layers"] = tuple(kwargs["layers"])
        return cls(**kwargs)
