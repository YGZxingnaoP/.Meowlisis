# -*- coding: utf-8 -*-
# func/llm_active/port/meowllm.py
# 主动回复独立 MeowLLM 端口（本地子服务，OpenAI 兼容）
#
# 协议在 func/meowllm/（基础设施）；本文件只读主动回复自己的配置并转发。
# 注意：llm_active 的 deepseek 端口读的是 func.llm.config.LLMConfig（沿用既有约定），
# 这里同样读它 —— 配置可以复用，**端口不复用**。

from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.meowllm import MeowLLMClient


class AutoMeowLLM:
    """主动回复 MeowLLM 客户端"""

    provider = "meowllm"

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        if config is None:
            from func.llm.config import LLMConfig
            config = LLMConfig()
        self.config = cfg = config
        self.engine = MeowLLMClient(
            label="llm_active",
            temperature=getattr(cfg, "temperature", None),
            max_tokens=getattr(cfg, "max_tokens", None),
        )
        self.client = self.engine.client
        self.base_url = self.engine.base_url
        self.model = self.engine.model
        self.temperature = self.engine.temperature
        self.max_tokens = self.engine.max_tokens

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, options: Optional[Dict] = None,
             enable_thinking=None, **kwargs):
        return self.engine.chat(messages, tools=tools, tool_choice=tool_choice,
                                options=options, enable_thinking=enable_thinking)

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    enable_thinking=None, **kwargs):
        return self.engine.chat_stream(messages, tools=tools,
                                       tool_choice=tool_choice, options=options,
                                       enable_thinking=enable_thinking)


MeowLLMLLM = AutoMeowLLM
