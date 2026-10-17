# -*- coding: utf-8 -*-
"""AsyncReasoning 引擎包。

分层（严格单向依赖，见 docs/notes/PLAN_AsyncReasoning_重构方案.md §4.2）：

    compat    ← 版本适配，唯一知道 transformers 内部 API 的地方
    blocks    ← 纯数据：三块 KV 的布局与 delta 角度表
    rope      ← 纯数学：把 delta 角度施加到 query 上
    attention ← 自定义 attention（注册进 transformers 的派发表）
    prompts   ← 只有字符串
    mode      ← 模式切换（yes/no 探针）
    reference ← 物理重排参考实现（对拍基准 & 降级路径）
    loop      ← 双流调度
    engine    ← 兑现 MeowLLMEngineBase 契约

不 import server，不被 server 内部细节依赖。
"""

from meowllm.engine.dualstream.engine import AsyncHFEngine

__all__ = ["AsyncHFEngine"]
