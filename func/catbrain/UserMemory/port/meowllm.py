# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/port/meowllm.py
# 用户记忆独立 MeowLLM 端口（本地子服务，OpenAI 兼容）
#
# 协议在 func/meowllm/（基础设施）；本文件只读用户记忆自己的配置并转发。

import re
from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.meowllm import MeowLLMClient
from func.catbrain.catbrain import MeowCatBrainConfig


class MeowUserMemoryMeowLLM:
    """用户记忆独立 MeowLLM 客户端"""

    provider = "meowllm"

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        self.config = cfg = config if config is not None else MeowCatBrainConfig()
        self.engine = MeowLLMClient(
            label="user_memory",
            temperature=getattr(cfg, "user_memory_temperature", None),
            max_tokens=getattr(cfg, "user_memory_max_tokens", None),
        )
        self.client = self.engine.client
        self.base_url = self.engine.base_url
        self.model = self.engine.model
        self.temperature = self.engine.temperature
        self.max_tokens = self.engine.max_tokens

    @staticmethod
    def _clean_resp_content(resp):
        try:
            if resp and getattr(resp, "choices", None):
                content = getattr(resp.choices[0].message, "content", None)
                if isinstance(content, str) and content:
                    resp.choices[0].message.content = re.sub(
                        r"【[^】]*】", "", content).strip()
        except Exception:
            pass
        return resp

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, options: Optional[Dict] = None,
             enable_thinking=None, **kwargs):
        return self._clean_resp_content(
            self.engine.chat(messages, tools=tools, tool_choice=tool_choice,
                             options=options, enable_thinking=enable_thinking))

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    enable_thinking=None, **kwargs):
        return self.engine.chat_stream(messages, tools=tools,
                                       tool_choice=tool_choice, options=options,
                                       enable_thinking=enable_thinking)


MeowLLMLLM = MeowUserMemoryMeowLLM
