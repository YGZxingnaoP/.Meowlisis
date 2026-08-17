# -*- coding: utf-8 -*-
# func/catbrain/UserMemory/port/aliyun.py
# 用户记忆独立 Qwen（阿里云）端口（OpenAI 兼容，支持 function calling 与思考模式）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig


class MeowUserMemoryAliyunLLM:
    """用户记忆独立 Qwen（阿里云百炼）客户端（temperature 0.7，思考强度高）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = MeowCatBrainConfig()
        self.api_key = cfg.user_aliyun_api_key
        self.base_url = cfg.user_aliyun_base_url
        self.model = cfg.user_aliyun_model
        self.temperature = cfg.user_temperature
        self.max_tokens = cfg.user_max_tokens
        self.enable_thinking = cfg.user_enable_thinking

        self.client = None
        if not self.api_key:
            self.log.error("用户记忆 Qwen（阿里云）API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化用户记忆 Qwen 客户端失败: {e}")

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
        # 思考强度高：通过 enable_thinking 参数开启
        params["extra_body"] = {"enable_thinking": self.enable_thinking}
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"用户记忆 Qwen 调用异常: {e}")
            return None
