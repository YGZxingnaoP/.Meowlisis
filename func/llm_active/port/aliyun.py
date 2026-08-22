# -*- coding: utf-8 -*-
# func/llm_active/port/aliyun.py
# 主动回复阿里云百炼端口（复用 llm 配置，max_tokens 两倍且上限 2048）

import re
from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.llm.config import LLMConfig


class AutoAliyunLLM:
    """主动回复阿里云百炼客户端（OpenAI 兼容，支持 function calling 与流式）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = LLMConfig()
        self.api_key = cfg.aliyun_api_key
        self.base_url = cfg.aliyun_base_url
        self.model = cfg.aliyun_model
        self.temperature = cfg.aliyun_temperature
        self.max_tokens = min(cfg.aliyun_max_tokens * 2, 2048)
        self.top_p = cfg.aliyun_top_p
        self.enable_thinking = cfg.aliyun_enable_thinking

        self.client = None
        if not self.api_key:
            self.log.error("主动回复阿里云百炼 API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.log.info(f"主动回复阿里云百炼客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"初始化主动回复阿里云百炼客户端失败: {e}")

    def _thinking_params(self, options):
        """构建思考模式参数（origin 可覆盖开启深度思考）"""
        enable = self.enable_thinking
        if options and 'enable_thinking' in options:
            enable = options.get('enable_thinking')
        return {"parameters": {"enable_thinking": bool(enable)}}

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
             tool_choice=None, options: Optional[Dict] = None):
        """非流式对话，返回完整响应（用于 inherit 工具调用）"""
        if not self.client:
            return None
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "extra_body": self._thinking_params(options),
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        try:
            resp = self.client.chat.completions.create(**params)
            return self._clean_resp_content(resp)
        except Exception as e:
            self.log.error(f"主动回复阿里云百炼调用异常: {e}")
            return None

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    options: Optional[Dict] = None, tool_choice=None):
        """流式对话，返回流式响应迭代器（用于 origin 深度思考输出）"""
        if not self.client:
            return iter([])
        params = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "extra_body": self._thinking_params(options),
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"主动回复阿里云百炼流式调用异常: {e}")
            return iter([])
