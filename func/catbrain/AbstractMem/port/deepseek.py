# -*- coding: utf-8 -*-
# func/catbrain/AbstractMem/port/deepseek.py
# 摘要独立 DeepSeek 端口（OpenAI 兼容，支持 function calling）

import re
from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig


class MeowAbstractDeepSeekLLM:
    """摘要独立 DeepSeek 客户端（功能与对话 LLM 完全独立）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = MeowCatBrainConfig()
        self.api_key = cfg.ab_deepseek_api_key
        self.base_url = cfg.ab_deepseek_base_url
        self.model = cfg.ab_deepseek_model
        self.temperature = cfg.ab_deepseek_temperature
        self.max_tokens = cfg.ab_deepseek_max_tokens

        self.client = None
        if not self.api_key:
            self.log.error("摘要 DeepSeek API Key 未配置")
            return
        try:
            # 关掉 SDK 自动重试：超时/失败要立刻降级，不能 3 倍放大主链等待
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url,
                                 timeout=60, max_retries=0)
        except Exception as e:
            self.log.error(f"初始化摘要 DeepSeek 客户端失败: {e}")

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
             tool_choice=None, temperature=None, max_tokens=None, timeout=None):
        """非流式对话，返回完整响应对象

        timeout: 单次请求超时（秒）。判官调用传短超时，摘要沿用客户端默认值。
        """
        if not self.client:
            return None
        params = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        if timeout is not None:
            params["timeout"] = timeout
        if temperature is not None:
            params["temperature"] = temperature
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        # 强制 tool_choice 与思考模式互斥（API 直接 400），摘要判定必须关思考
        params["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            resp = self.client.chat.completions.create(**params)
            return self._clean_resp_content(resp)
        except Exception as e:
            self.log.error(f"摘要 DeepSeek 调用异常: {e}")
            return None
