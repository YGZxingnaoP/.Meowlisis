# -*- coding: utf-8 -*-
# func/catbrain/AbstractMem/port/gemini.py
# 摘要独立 Google Gemini 端口（OpenAI 兼容，支持 function calling）

import re
from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig


class MeowAbstractGeminiLLM:
    """摘要独立 Google Gemini 客户端（功能与对话 LLM 完全独立）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = MeowCatBrainConfig()
        self.api_key = cfg.ab_gemini_api_key
        self.base_url = cfg.ab_gemini_base_url
        self.model = cfg.ab_gemini_model
        self.temperature = cfg.ab_gemini_temperature
        self.max_tokens = cfg.ab_gemini_max_tokens

        self.client = None
        if not self.api_key:
            self.log.error("摘要 Google Gemini API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化摘要 Google Gemini 客户端失败: {e}")

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
        # Gemini 强制工具调用时降到最低思考档（Gemini 3 无法完全关闭）
        if tool_choice:
            params["reasoning_effort"] = "low"
        try:
            resp = self.client.chat.completions.create(**params)
            return self._clean_resp_content(resp)
        except Exception as e:
            self.log.error(f"摘要 Google Gemini 调用异常: {e}")
            return None
