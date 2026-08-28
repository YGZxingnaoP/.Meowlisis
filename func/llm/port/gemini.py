# -*- coding: utf-8 -*-
# func/llm/port/gemini.py
# Google Gemini 流式调用（基于 OpenAI 兼容接口，支持 function calling）

from typing import List, Dict, Optional
from openai import OpenAI

from func.log.default_log import DefaultLog
from func.llm.config import LLMConfig


class GeminiLLM:
    """Google Gemini 流式客户端（OpenAI 兼容接口）

    - base_url 使用 Gemini 官方 OpenAI 兼容端点；
    - 思考控制使用 reasoning_effort（官方 OpenAI 兼容参数），
      low/medium/high 对应 Gemini 思考档位；Gemini 3 系列无法完全关闭思考。
    """

    def __init__(self, config: Optional[LLMConfig] = None):
        self.log = DefaultLog().getLogger()
        self.config = config if config is not None else LLMConfig()
        self.api_key = self.config.gemini_api_key
        self.base_url = self.config.gemini_base_url
        self.model = self.config.gemini_model
        self.temperature = self.config.gemini_temperature
        self.max_tokens = self.config.gemini_max_tokens
        self.top_p = self.config.gemini_top_p
        self.enable_thinking = self.config.gemini_enable_thinking

        if not self.api_key:
            self.log.error("Google Gemini API Key 未配置")
            self.client = None
            return

        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.log.info(f"Google Gemini 客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"初始化 Google Gemini 客户端失败: {e}")
            self.client = None

    def _build_params(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None,
                      options: Optional[Dict] = None, tool_choice=None,
                      enable_thinking: Optional[bool] = None) -> Dict:
        """构建请求参数（思考控制使用 reasoning_effort）"""
        params = {
            "model": options.get("model", self.model) if options else self.model,
            "messages": messages,
            "stream": True,
            "temperature": options.get("temperature", self.temperature) if options else self.temperature,
            "max_tokens": options.get("max_tokens", self.max_tokens) if options else self.max_tokens,
            "top_p": options.get("top_p", self.top_p) if options else self.top_p,
        }
        # 附加 tools（function calling）
        if tools:
            params["tools"] = tools
        # 强制指定工具（function calling）
        if tool_choice:
            params["tool_choice"] = tool_choice
        # 思考开关：Gemini 官方 OpenAI 兼容参数 reasoning_effort（low/medium/high/none）
        # 显式参数优先于配置；Gemini 3 系列无法完全关闭思考，low 为最低档
        use_thinking = self.enable_thinking if enable_thinking is None else enable_thinking
        params["reasoning_effort"] = "high" if use_thinking else "low"
        return params

    def chat_stream(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None,
                    options: Optional[Dict] = None, tool_choice=None,
                    enable_thinking: Optional[bool] = None):
        """流式对话，返回 OpenAI 流式响应迭代器（支持 tools 触发 function calling）"""
        if not self.client:
            self.log.error("Google Gemini 客户端不可用")
            return iter([])

        params = self._build_params(messages, tools=tools, options=options, tool_choice=tool_choice,
                                    enable_thinking=enable_thinking)
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"Google Gemini 流式调用异常: {e}")
            return iter([])
