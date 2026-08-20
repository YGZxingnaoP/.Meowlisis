# -*- coding: utf-8 -*-
# func/toolbox/port/aliyun.py
# Toolbox 独立 Qwen（阿里云）端口（OpenAI 兼容，支持 function calling 与流式）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.config import TBoxConfig
from func.tools.text_cleaner import clean_resp_content


class TBoxAliyunLLM:
    """Toolbox 独立 Qwen（阿里云百炼）客户端（父级 toolcalls / NapCat 复用，可注入外部 config）"""

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        cfg = config if config is not None else TBoxConfig()
        self.api_key = cfg.aliyun_api_key
        self.base_url = cfg.aliyun_base_url
        self.model = cfg.aliyun_model
        self.temperature = cfg.aliyun_temperature
        self.max_tokens = cfg.aliyun_max_tokens
        # NapCat 复用 func/llm 配置时，支持携带 top_p / enable_thinking
        self.top_p = getattr(cfg, 'aliyun_top_p', None)
        self.enable_thinking = getattr(cfg, 'aliyun_enable_thinking', False)

        self.client = None
        if not self.api_key:
            self.log.error("Toolbox Qwen（阿里云）API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化 Toolbox Qwen 客户端失败: {e}")

    @staticmethod
    def _thinking_enabled(level) -> bool:
        """将思考级别映射为布尔开关（阿里云 Qwen 当前仅有开/关两档）"""
        return level in ("low", "medium", "high", "enabled", True)

    def _build_extra_body(self, tool_choice, thinking_level):
        """构建 enable_thinking extra_body：工具调用强制禁用思考"""
        enabled = False
        if not tool_choice and self._thinking_enabled(thinking_level):
            enabled = True
        return {"enable_thinking": enabled}

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, enable_thinking=None):
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
        if enable_thinking is None:
            enable_thinking = self.enable_thinking
        level = "enabled" if enable_thinking else "off"
        params["extra_body"] = self._build_extra_body(tool_choice, level)
        try:
            resp = self.client.chat.completions.create(**params)
            return clean_resp_content(resp)
        except Exception as e:
            self.log.error(f"Toolbox Qwen 调用异常: {e}")
            return None

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    thinking_level: str = "off"):
        """流式对话，返回 OpenAI 流式响应迭代器（支持 tools 触发 function calling）"""
        if not self.client:
            self.log.error("Toolbox Qwen 客户端不可用")
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
        params["extra_body"] = self._build_extra_body(tool_choice, thinking_level)
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"Toolbox Qwen 流式调用异常: {e}")
            return iter([])
