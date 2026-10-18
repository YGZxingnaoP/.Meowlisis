# -*- coding: utf-8 -*-
# func/llm_active/origin/vision/port/meowllm.py
# 主动回复·视觉 独立 MeowLLM 端口（本地子服务，OpenAI 兼容）
#
# 视觉模块原本只有 aliyun；MeowLLM 走的是本地模型（Qwen3 系不带视觉权重时
# 只能当纯文本用），所以这里是"可选"的第四种口径，行为与其他端口一致。

from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.meowllm import MeowLLMClient
from func.llm_active.origin.vision.config import AutoVisionConfig


class AutoVisionMeowLLM:
    """主动回复视觉 MeowLLM 客户端"""

    provider = "meowllm"

    def __init__(self, config: Optional[AutoVisionConfig] = None):
        self.log = DefaultLog().getLogger()
        self.config = cfg = config if config is not None else AutoVisionConfig()
        self.engine = MeowLLMClient(
            label="auto_vision",
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


MeowLLMLLM = AutoVisionMeowLLM
