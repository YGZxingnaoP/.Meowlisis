# -*- coding: utf-8 -*-
# func/toolbox/port/gemini.py
# Toolbox 独立 Google Gemini 端口（OpenAI 兼容，支持 function calling 与流式）

import re
from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.config import TBoxConfig


class TBoxGeminiLLM:
    """Toolbox 独立 Google Gemini 客户端（父级 toolcalls / NapCat 复用，可注入外部 config）"""

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        cfg = config if config is not None else TBoxConfig()
        self.api_key = cfg.gemini_api_key
        self.base_url = cfg.gemini_base_url
        self.model = cfg.gemini_model
        self.temperature = cfg.gemini_temperature
        self.max_tokens = cfg.gemini_max_tokens
        # NapCat 复用 func/llm 配置时，支持携带 top_p / enable_thinking
        self.top_p = getattr(cfg, 'gemini_top_p', None)
        self.enable_thinking = getattr(cfg, 'gemini_enable_thinking', False)

        self.client = None
        if not self.api_key:
            self.log.error("Toolbox Google Gemini API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化 Toolbox Google Gemini 客户端失败: {e}")

    @staticmethod
    def _thinking_enabled(level) -> bool:
        """将思考级别映射为布尔开关（Gemini 通过 reasoning_effort 分档）"""
        return level in ("low", "medium", "high", "enabled", True)

    def _reasoning_effort(self, tool_choice, thinking_level):
        """构建 reasoning_effort：工具调用强制最低档，否则按级别映射。

        Gemini 3 系列无法完全关闭思考，off 也映射到最低档 low（Gemini 2.5 可改用 none）。
        """
        if tool_choice:
            return "low"
        level = str(thinking_level or "off").strip().lower()
        mapping = {
            "off": "low",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "enabled": "medium",
        }
        return mapping.get(level, "low")

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
             tool_choice=None, enable_thinking=None):
        """非流式对话，返回完整响应对象（用于 toolcalls 判断）"""
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
        if enable_thinking is None:
            enable_thinking = self.enable_thinking
        level = "enabled" if enable_thinking else "off"
        params["reasoning_effort"] = self._reasoning_effort(tool_choice, level)
        try:
            resp = self.client.chat.completions.create(**params)
            return self._clean_resp_content(resp)
        except Exception as e:
            self.log.error(f"Toolbox Google Gemini 调用异常: {e}")
            return None

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    thinking_level: str = "off"):
        """流式对话，返回 OpenAI 流式响应迭代器（支持 tools 触发 function calling）"""
        if not self.client:
            self.log.error("Toolbox Google Gemini 客户端不可用")
            return iter([])
        params = {
            "model": options.get("model", self.model) if options else self.model,
            "messages": messages,
            "stream": True,
            "temperature": options.get("temperature", self.temperature) if options else self.temperature,
            "max_tokens": options.get("max_tokens", self.max_tokens) if options else self.max_tokens,
        }
        top_p = None
        if options and "top_p" in options:
            top_p = options["top_p"]
        elif self.top_p is not None:
            top_p = self.top_p
        if top_p is not None:
            params["top_p"] = top_p
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        params["reasoning_effort"] = self._reasoning_effort(tool_choice, thinking_level)
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"Toolbox Google Gemini 流式调用异常: {e}")
            return iter([])
