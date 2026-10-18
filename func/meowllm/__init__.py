# -*- coding: utf-8 -*-
# func/meowllm/__init__.py
"""MeowLLM 本地子服务的**基础设施**（不是某个模块的 port）。

分层约定（这也是本项目一直以来的风格）
--------------------------------------
    func/log、func/config、func/tools   基础设施，谁都能用
    func/<模块>/port/                   该模块**自己的** LLM 端点实现

所以：

* 本包只放"怎么跟 MeowLLM 说话"——端点、协议字段、思考档位、按用户记忆。
  它不认识任何模块，也不读任何模块的配置。
* `func/<模块>/port/meowllm.py` 才是各模块的端口实现：读自己的配置、决定默认
  温度/长度，然后转发给本包的 client。
* **任何模块都不应该 import 另一个模块的 port。** 之前 `func/llm/port/meowllm.py`
  被 40 多个文件直接引用，等于把 llm 模块的端口变成了全局单例，破坏了
  "每个模块的 port 独立" 这条约定 —— 这个包就是为了把协议抽出来、让各端口
  重新变薄而存在的。
"""

from func.meowllm.config import (
    base_url,
    config_path,
    conversation_tokens,
    data,
    gen,
    get,
    model_name,
    save,
    thinking_level,
)
from func.meowllm.client import MeowLLMClient, MeowLLMStreamTap
from func.meowllm import memory

__all__ = [
    "MeowLLMClient", "MeowLLMStreamTap", "memory",
    "base_url", "config_path", "conversation_tokens", "data", "gen", "get",
    "model_name", "save", "thinking_level",
]
