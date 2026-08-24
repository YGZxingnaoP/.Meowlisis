# -*- coding: utf-8 -*-
# func/meowsinger/port/deepseek.py
# meowsinger 独立 DeepSeek 端口（OpenAI 兼容，支持 function calling 与流式）
import re
from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog


class MeowSingerDeepSeekLLM:
    """meowsinger 独立 DeepSeek 客户端，apikey 与参数完全独立"""

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        cfg = config
        self.api_key = cfg.deepseek_api_key
        self.base_url = cfg.deepseek_base_url
        self.model = cfg.deepseek_model
        self.temperature = cfg.deepseek_temperature
        self.max_tokens = cfg.deepseek_max_tokens

        self.client = None
        if not self.api_key:
            self.log.error("meowsinger DeepSeek API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化 meowsinger DeepSeek 客户端失败: {e}")

    @staticmethod
    def _clean_resp_content(resp):
        try:
            if resp and getattr(resp, "choices", None):
                content = getattr(resp.choices[0].message, "content", None)
                if isinstance(content, str) and content:
                    resp.choices[0].message.content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
        except Exception:
            pass
        return resp

    def chat(self, messages, tools=None, tool_choice=None, max_tokens=None, temperature=None):
        if not self.client:
            return None
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        try:
            resp = self.client.chat.completions.create(**params)
            return self._clean_resp_content(resp)
        except Exception as e:
            self.log.error(f"meowsinger DeepSeek 调用异常: {e}")
            return None

    def chat_stream(self, messages, tools=None, tool_choice=None):
        if not self.client:
            return iter([])
        params = {
            "model": self.model,
            "messages": messages,
            "stream": True,
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
            self.log.error(f"meowsinger DeepSeek 流式调用异常: {e}")
            return iter([])
