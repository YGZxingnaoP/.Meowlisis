# -*- coding: utf-8 -*-
# func/llm/port/meowllm.py
"""`llm` 模块自己的 MeowLLM 端口（主对话链路专用）。

协议与端点都在 `func/meowllm/`（基础设施）里；这里只负责：
    * 读 llm 模块关心的默认值（温度 / max_tokens / 思考档位）
    * 暴露主链路需要的形态（`chat` / `chat_stream`，支持 tools 与 options）

⚠ 其它模块**不要** import 本文件。每个模块有自己的
`func/<模块>/port/meowllm.py`，它们同样只是 `func.meowllm.MeowLLMClient`
的薄包装 —— "每个模块的 port 独立" 这条约定靠这个保持。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from func.meowllm import MeowLLMClient, config as meowllm_config


class MeowLLMLLM:
    """主对话链路的 MeowLLM 客户端。"""

    def __init__(self, config=None, *, max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None,
                 label: str = "llm"):
        self.engine = MeowLLMClient(
            label=label,
            temperature=temperature,
            max_tokens=(max_tokens if max_tokens is not None
                        else meowllm_config.gen("talk_max_tokens", 256)),
        )
        self.log = self.engine.log
        self.base_url = self.engine.base_url
        self.model = self.engine.model
        self.temperature = self.engine.temperature
        self.top_p = self.engine.top_p
        self.top_k = self.engine.top_k
        self.repeat_penalty = self.engine.repeat_penalty
        self.talk_max_tokens = self.engine.max_tokens
        self.thinking_level = self.engine.thinking_level

    @property
    def client(self):
        return self.engine.client

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, enable_thinking=None,
             options: Optional[Dict] = None, thinking_level=None, **kwargs):
        return self.engine.chat(messages, tools=tools, tool_choice=tool_choice,
                                enable_thinking=enable_thinking,
                                options=options, thinking_level=thinking_level)

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    enable_thinking=None, thinking_level=None, **kwargs):
        return self.engine.chat_stream(messages, tools=tools,
                                       tool_choice=tool_choice, options=options,
                                       enable_thinking=enable_thinking,
                                       thinking_level=thinking_level)
