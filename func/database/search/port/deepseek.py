# -*- coding: utf-8 -*-
# func/database/search/port/deepseek.py
# 搜索模块独立 DeepSeek 端口（与 llm 端口相同，独立 apikey）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.database.config import CatLearnConfig
from func.tools.text_cleaner import clean_resp_content


class CatLearnSearchDeepSeekLLM:
    """搜索模块 DeepSeek 客户端（用于搜索任务决策 / keys 提取 / 摘要）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = CatLearnConfig()
        self.api_key = cfg.search_deepseek_api_key
        self.base_url = cfg.search_deepseek_base_url
        self.model = cfg.search_deepseek_model
        self.temperature = cfg.search_temperature
        self.max_tokens = cfg.search_deepseek_max_tokens

        self.client = None
        if not self.api_key:
            self.log.error("搜索模块 DeepSeek API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化搜索 DeepSeek 客户端失败: {e}")

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, temperature=None, enable_thinking: bool = False):
        """非流式对话，返回完整响应对象"""
        if not self.client:
            return None
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        # DeepSeek 强制工具调用时需禁用 thinking；深度思考决策时开启
        if tool_choice:
            params["extra_body"] = {"thinking": {"type": "disabled"}}
        elif enable_thinking:
            params["extra_body"] = {"thinking": {"type": "enabled"}}
        try:
            resp = self.client.chat.completions.create(**params)
            return clean_resp_content(resp)
        except Exception as e:
            self.log.error(f"搜索 DeepSeek 调用异常: {e}")
            return None

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, temperature=None):
        """流式对话，返回流式迭代器"""
        if not self.client:
            return iter([])
        params = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"搜索 DeepSeek 流式调用异常: {e}")
            return iter([])
