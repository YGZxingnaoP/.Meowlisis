# -*- coding: utf-8 -*-
# func/database/search/port/aliyun.py
# 搜索模块独立 Qwen（阿里云）端口（与 llm 端口相同，独立 apikey）

import re
from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.database.config import CatLearnConfig


class CatLearnSearchAliyunLLM:
    """搜索模块 Qwen（阿里云）客户端（用于搜索任务决策 / keys 提取 / 摘要）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = CatLearnConfig()
        self.api_key = cfg.search_aliyun_api_key
        self.base_url = cfg.search_aliyun_base_url
        self.model = cfg.search_aliyun_model
        self.temperature = cfg.search_temperature
        self.max_tokens = cfg.search_aliyun_max_tokens

        self.client = None
        if not self.api_key:
            self.log.error("搜索模块 Qwen（阿里云）API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化搜索 Qwen 客户端失败: {e}")

    @staticmethod
    def _clean_resp_content(resp):
        """去除响应 content 中的全角方括号【】及其内容"""
        try:
            if resp and getattr(resp, "choices", None):
                content = getattr(resp.choices[0].message, "content", None)
                if isinstance(content, str) and content:
                    resp.choices[0].message.content = re.sub(r"【[^】]*】", "", content).strip()
        except Exception:
            pass
        return resp

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
        # 深度思考决策时开启 qwen3 思考
        if tool_choice:
            params["extra_body"] = {"parameters": {"enable_thinking": False}}
        elif enable_thinking:
            params["extra_body"] = {"parameters": {"enable_thinking": True}}
        try:
            resp = self.client.chat.completions.create(**params)
            return self._clean_resp_content(resp)
        except Exception as e:
            self.log.error(f"搜索 Qwen 调用异常: {e}")
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
            self.log.error(f"搜索 Qwen 流式调用异常: {e}")
            return iter([])
