# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/port/meowllm.py
# 绘画模型 MeowLLM 端口（本地子服务，OpenAI 兼容）
#
# 继承 TBFluxPainterLLMBase 只是为了跟另外两个端口保持同一套接口形状；
# 组包走 func/meowllm/ 的协议（`meowllm` 子块 + 顶层 top_k），不复用基类的
# `_mk_params`，因为基类那套是给云端平台用的（extra_body 只有 thinking）。

from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.meowllm import MeowLLMClient
from func.toolbox.flux_painter.port.base import TBFluxPainterLLMBase


class TBFluxPainterMeowLLM(TBFluxPainterLLMBase):
    """绘画 MeowLLM 客户端"""

    provider = "meowllm"

    def __init__(self, config):
        super().__init__(config)
        self.log = DefaultLog().getLogger()
        self.engine = MeowLLMClient(
            label="flux_painter",
            temperature=getattr(config, "temperature", None),
            max_tokens=getattr(config, "max_tokens", None),
        )
        self.client = self.engine.client
        self.base_url = self.engine.base_url
        self.model = self.engine.model
        self.temperature = self.engine.temperature
        self.max_tokens = self.engine.max_tokens

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, options: Optional[Dict] = None,
             enable_thinking: Optional[bool] = None):
        return self.engine.chat(messages, tools=tools, tool_choice=tool_choice,
                                options=options, enable_thinking=enable_thinking)

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    enable_thinking: Optional[bool] = None):
        return self.engine.chat_stream(messages, tools=tools,
                                       tool_choice=tool_choice, options=options,
                                       enable_thinking=enable_thinking)


MeowLLMLLM = TBFluxPainterMeowLLM
