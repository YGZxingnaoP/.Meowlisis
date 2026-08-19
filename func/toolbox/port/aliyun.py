# -*- coding: utf-8 -*-
# func/toolbox/port/aliyun.py
# Toolbox 独立 Qwen（阿里云）端口（OpenAI 兼容，支持 function calling）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.config import TBoxConfig


class TBoxAliyunLLM:
    """Toolbox 独立 Qwen（阿里云百炼）客户端（父级 toolcalls 判断用）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = TBoxConfig()
        self.api_key = cfg.aliyun_api_key
        self.base_url = cfg.aliyun_base_url
        self.model = cfg.aliyun_model
        self.temperature = cfg.aliyun_temperature
        self.max_tokens = cfg.aliyun_max_tokens

        self.client = None
        if not self.api_key:
            self.log.error("Toolbox Qwen（阿里云）API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化 Toolbox Qwen 客户端失败: {e}")

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None):
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
        params["extra_body"] = {"enable_thinking": False}
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"Toolbox Qwen 调用异常: {e}")
            return None
