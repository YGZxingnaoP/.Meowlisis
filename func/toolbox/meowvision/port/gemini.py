# -*- coding: utf-8 -*-
# func/toolbox/meowvision/port/gemini.py
# MeowVision 视觉理解模型端口（Google Gemini，OpenAI 兼容，非流式）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.meowvision.config import TBVisionConfig


class TBVisionGeminiLLM:
    """MeowVision 视觉理解客户端（多模态，Google Gemini）

    - 非流式调用，返回完整响应对象（含 message.content 与 message.tool_calls）；
    - 深度思考过程位于 message.reasoning_content（若模型输出），正式回答位于 message.content；
    - 支持 function calling：tools / tool_choice 透传。
    """

    def __init__(self, config: Optional[TBVisionConfig] = None):
        self.log = DefaultLog().getLogger()
        cfg = config if config is not None else TBVisionConfig()
        self.api_key = cfg.gemini_api_key
        self.base_url = cfg.gemini_base_url
        self.model = cfg.gemini_model
        self.max_tokens = cfg.gemini_max_tokens
        self.temperature = cfg.gemini_temperature
        self.top_p = cfg.gemini_top_p

        self.client = None
        if not self.api_key:
            self.log.error("MeowVision Google Gemini 视觉 API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.log.info(f"MeowVision Google Gemini 视觉客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"初始化 MeowVision Google Gemini 视觉客户端失败: {e}")

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None):
        """非流式对话，返回完整响应对象（含 content 与 tool_calls），失败返回 None。"""
        if not self.client:
            self.log.error("MeowVision Google Gemini 视觉客户端不可用")
            return None
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.top_p is not None:
            params["top_p"] = self.top_p
        if tools:
            params["tools"] = tools
        if tool_choice is not None:
            params["tool_choice"] = tool_choice
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"MeowVision Google Gemini 视觉调用异常: {e}")
            return None
