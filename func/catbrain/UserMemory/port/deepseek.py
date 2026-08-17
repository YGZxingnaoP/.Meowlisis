# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/port/deepseek.py
# 用户记忆独立 DeepSeek 端口（OpenAI 兼容，支持 function calling 与思考模式）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig


class MeowUserMemoryDeepSeekLLM:
    """用户记忆独立 DeepSeek 客户端（temperature 0.7，思考强度高）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = MeowCatBrainConfig()
        self.api_key = cfg.user_deepseek_api_key
        self.base_url = cfg.user_deepseek_base_url
        self.model = cfg.user_deepseek_model
        self.temperature = cfg.user_temperature
        self.max_tokens = cfg.user_max_tokens
        self.enable_thinking = cfg.user_enable_thinking

        self.client = None
        if not self.api_key:
            self.log.error("用户记忆 DeepSeek API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化用户记忆 DeepSeek 客户端失败: {e}")

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None):
        """非流式对话，返回完整响应对象（用于用户信息工具调用）"""
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
        # 思考强度高：关闭思考时才附加 disabled，开启时使用模型默认思考行为
        if not self.enable_thinking:
            params["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"用户记忆 DeepSeek 调用异常: {e}")
            return None
