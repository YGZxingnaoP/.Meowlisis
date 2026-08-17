# -*- coding: utf-8 -*-
# func/catbrain/AbstractMem/port/aliyun.py
# 摘要独立 Qwen（阿里云）端口（OpenAI 兼容，支持 function calling）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig


class MeowAbstractAliyunLLM:
    """摘要独立 Qwen（阿里云百炼）客户端（功能与对话 LLM 完全独立）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = MeowCatBrainConfig()
        self.api_key = cfg.ab_aliyun_api_key
        self.base_url = cfg.ab_aliyun_base_url
        self.model = cfg.ab_aliyun_model
        self.temperature = cfg.ab_aliyun_temperature
        self.max_tokens = cfg.ab_aliyun_max_tokens

        self.client = None
        if not self.api_key:
            self.log.error("摘要 Qwen（阿里云）API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化摘要 Qwen 客户端失败: {e}")

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None):
        """非流式对话，返回完整响应对象（用于摘要工具调用）"""
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
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"摘要 Qwen 调用异常: {e}")
            return None
