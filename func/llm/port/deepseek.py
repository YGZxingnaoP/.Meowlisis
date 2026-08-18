# -*- coding: utf-8 -*-
# func/llm/port/deepseek.py
# DeepSeek 流式调用（基于 OpenAI 兼容接口，支持 function calling）

from typing import List, Dict, Optional
from openai import OpenAI

from func.log.default_log import DefaultLog
from func.llm.config import LLMConfig


class DeepSeekLLM:
    """DeepSeek 流式客户端（OpenAI 兼容接口）"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.log = DefaultLog().getLogger()
        self.config = config if config is not None else LLMConfig()
        self.api_key = self.config.deepseek_api_key
        self.base_url = self.config.deepseek_base_url
        self.model = self.config.deepseek_model
        self.temperature = self.config.deepseek_temperature
        self.max_tokens = self.config.deepseek_max_tokens
        self.top_p = self.config.deepseek_top_p
        self.enable_thinking = self.config.deepseek_enable_thinking

        if not self.api_key:
            self.log.error("DeepSeek API Key 未配置")
            self.client = None
            return

        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.log.info(f"DeepSeek 客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"初始化 DeepSeek 客户端失败: {e}")
            self.client = None

    def _build_params(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None,
                      options: Optional[Dict] = None, tool_choice=None) -> Dict:
        """构建请求参数"""
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
        # 默认关闭思考模式（deepseek 通过 thinking.type 控制）
        if not self.enable_thinking:
            params["extra_body"] = {"thinking": {"type": "disabled"}}
        return params

    def chat_stream(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None,
                    options: Optional[Dict] = None, tool_choice=None):
        """流式对话，返回 OpenAI 流式响应迭代器（支持 tools 触发 function calling）"""
        if not self.client:
            self.log.error("DeepSeek 客户端不可用")
            return iter([])

        params = self._build_params(messages, tools=tools, options=options, tool_choice=tool_choice)
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"DeepSeek 流式调用异常: {e}")
            return iter([])


