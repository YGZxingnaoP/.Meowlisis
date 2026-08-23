# -*- coding: utf-8 -*-
# func/toolbox/meowvision/port/aliyun.py
# MeowVision 视觉理解模型端口（阿里云百炼 / MaaS，OpenAI 兼容，非流式）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.meowvision.config import TBVisionConfig


class TBVisionAliyunLLM:
    """MeowVision 视觉理解客户端（多模态，仅阿里云平台）

    - 非流式调用，返回完整响应对象（含 message.content 与 message.tool_calls）；
    - 深度思考过程位于 message.reasoning_content（若模型输出），正式回答位于 message.content；
    - 支持 function calling：tools / tool_choice 透传。
    """

    def __init__(self, config: Optional[TBVisionConfig] = None):
        self.log = DefaultLog().getLogger()
        cfg = config if config is not None else TBVisionConfig()
        self.api_key = cfg.api_key
        self.base_url = cfg.base_url
        self.model = cfg.model
        self.max_tokens = cfg.max_tokens
        self.temperature = cfg.temperature
        self.top_p = cfg.top_p

        self.client = None
        if not self.api_key:
            self.log.error("MeowVision 阿里云视觉 API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.log.info(f"MeowVision 阿里云视觉客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"初始化 MeowVision 阿里云视觉客户端失败: {e}")

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None):
        """非流式对话，返回完整响应对象（含 content 与 tool_calls），失败返回 None。

        非流式下深度思考（reasoning_content）与 tool_calls 都能从响应中取得，
        上层可自行决定优先读取哪个。不传 tool_choice 时由模型自主决定是否调用工具。
        """
        if not self.client:
            self.log.error("MeowVision 阿里云视觉客户端不可用")
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
            self.log.error(f"MeowVision 阿里云视觉调用异常: {e}")
            return None
