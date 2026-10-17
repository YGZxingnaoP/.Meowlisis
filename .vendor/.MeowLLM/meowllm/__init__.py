# -*- coding: utf-8 -*-
"""MeowLLM —— 本地模型加载与认知编排服务。

对外只暴露两个前缀：
    数据面  /meowllm/v1/*        （OpenAI 兼容子集）
    控制面  /meowllm/control/*   （健康、统计、重载）

包名 `meowllm` 即命名空间；模块文件名不带前缀，类名一律 MeowLLM* 前缀。
"""

MeowLLM_VERSION = "0.1.0"
MeowLLM_API_VERSION = "meowllm/v1"
MeowLLM_V1_PREFIX = "/meowllm/v1"
MeowLLM_CONTROL_PREFIX = "/meowllm/control"

MEOWLLM_SERVICE_NAME = "MeowLLM"

__all__ = [
    "MeowLLM_VERSION",
    "MeowLLM_API_VERSION",
    "MeowLLM_V1_PREFIX",
    "MeowLLM_CONTROL_PREFIX",
    "MEOWLLM_SERVICE_NAME",
]
