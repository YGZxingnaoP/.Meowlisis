# -*- coding: utf-8 -*-
# func/toolbox/port/deepseek.py
# Toolbox 独立 DeepSeek 端口（OpenAI 兼容，支持 function calling）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.config import TBoxConfig


class TBoxDeepSeekLLM:
    """Toolbox 独立 DeepSeek 客户端（父级 toolcalls 判断用）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = TBoxConfig()
        self.api_key = cfg.deepseek_api_key
        self.base_url = cfg.deepseek_base_url
        self.model = cfg.deepseek_model
        self.temperature = cfg.deepseek_temperature
        self.max_tokens = cfg.deepseek_max_tokens

        self.client = None
        if not self.api_key:
            self.log.error("Toolbox DeepSeek API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化 Toolbox DeepSeek 客户端失败: {e}")

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None):
        """非流式对话，返回完整响应对象（用于父级 toolcalls 判断）"""
        if not self.client:
            return None
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        # 关闭思考模式，保证工具调用稳定
        params["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"Toolbox DeepSeek 调用异常: {e}")
            return None
