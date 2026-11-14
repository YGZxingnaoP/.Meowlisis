# -*- coding: utf-8 -*-

import os
from typing import Dict, List, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.flux_painter.port.base import TBFluxPainterLLMBase

DEFAULT_BASE_URL = os.environ.get("MEOWLLM_BASE_URL", "http://127.0.0.1:18100/meowllm/v1")
_LEVELS = ("off", "low", "medium", "high")

class TBFluxPainterMeowLLM(TBFluxPainterLLMBase):
    """绘画 MeowLLM 客户端"""

    provider = "meowllm"

    def __init__(self, config):
        """初始化。"""
        super().__init__(config)
        self.log = DefaultLog().getLogger()
        self.base_url = getattr(config, "meowllm_base_url", None) or DEFAULT_BASE_URL
        self.model = getattr(config, "meowllm_model", None) or "meowllm-local"
        self.temperature = float(getattr(config, "temperature", None) or 0.8)
        self.max_tokens = int(getattr(config, "max_tokens", None) or 1024)
        self.top_p = float(getattr(config, "top_p", None) or 0.9)
        self.top_k = int(getattr(config, "meowllm_top_k", None) or 40)
        self.repeat_penalty = float(getattr(config, "meowllm_repeat_penalty", None) or 1.05)
        self.thinking_level = str(getattr(config, "meowllm_thinking_level", None) or "off")

        try:
            self.client = OpenAI(api_key="meowllm-local", base_url=self.base_url)
            self.log.info(f"[flux_painter] MeowLLM 客户端初始化成功，端点: {self.base_url}")
        except Exception as e:
            self.log.error(f"[flux_painter] 初始化 MeowLLM 客户端失败: {e}")
            self.client = None

    @staticmethod
    def _resolve_level(enable_thinking=None, thinking_level=None) -> str:
        """解析思考档位。"""
        if thinking_level in _LEVELS:
            return thinking_level
        if enable_thinking is False:
            return "off"
        if enable_thinking is True:
            return "medium"
        return ""

    def _build_params(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                      options: Optional[Dict] = None, tool_choice=None,
                      enable_thinking: Optional[bool] = None,
                      thinking_level: Optional[str] = None,
                      stream: bool = True) -> Dict:
        """组装请求参数。"""
        options = options or {}
        params = {
            "model": options.get("model", self.model),
            "messages": messages,
            "stream": bool(stream),
            "temperature": options.get("temperature", self.temperature),
            "top_p": options.get("top_p", self.top_p),
            "max_tokens": options.get("max_tokens", self.max_tokens),
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice

        block: Dict = {}
        level = self._resolve_level(enable_thinking, thinking_level) or self.thinking_level
        if level:
            block["thinking_level"] = level
        owner = options.get("memory_owner")
        if owner:
            block["memory_owner"] = owner

        params["extra_body"] = {
            "top_k": int(options.get("top_k", self.top_k)),
            "repeat_penalty": float(options.get("repeat_penalty", self.repeat_penalty)),
            "meowllm": block,
        }
        return params

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, options: Optional[Dict] = None,
             enable_thinking: Optional[bool] = None, thinking_level=None):
        """非流式对话，返回完整响应。"""
        if not self.client:
            self.log.error("[flux_painter] MeowLLM 客户端不可用")
            return None
        params = self._build_params(messages, tools, options, tool_choice,
                                    enable_thinking, thinking_level, stream=False)
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"[flux_painter] MeowLLM 调用异常: {e}")
            return None

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    enable_thinking: Optional[bool] = None, thinking_level=None):
        """流式对话，返回增量迭代器。"""
        if not self.client:
            self.log.error("[flux_painter] MeowLLM 客户端不可用")
            return iter([])
        params = self._build_params(messages, tools, options, tool_choice,
                                    enable_thinking, thinking_level, stream=True)
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"[flux_painter] MeowLLM 流式调用异常: {e}")
            return iter([])
