# -*- coding: utf-8 -*-
# func/toolbox/meowvision/port/meowllm.py
# MeowVision 独立 MeowLLM 端口（本地子服务，OpenAI 兼容）
#
# 协议在 func/meowllm/（基础设施）；本文件只读视觉模块自己的配置并转发。
# 注意：本地模型不带视觉权重时只能当纯文本用，调用方要自己判断能不能给图。

from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.meowllm import MeowLLMClient
from func.toolbox.meowvision.config import TBVisionConfig


class TBVisionMeowLLM:
    """MeowVision MeowLLM 客户端"""

    provider = "meowllm"

    def __init__(self, config: Optional[TBVisionConfig] = None):
        self.log = DefaultLog().getLogger()
        self.config = cfg = config if config is not None else TBVisionConfig()
        self.engine = MeowLLMClient(
            label="meowvision",
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


MeowLLMLLM = TBVisionMeowLLM
