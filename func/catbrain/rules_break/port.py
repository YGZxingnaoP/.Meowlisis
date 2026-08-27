# -*- coding: utf-8 -*-
# func/catbrain/rules_break/port.py
# rules_break 独立 DeepSeek 审查端口（OpenAI 兼容，仅非流式 + tool_choice）

import re
from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.catbrain.rules_break.config import TBRulesBreakConfig


class TBRulesBreakPort:
    """rules_break 独立 DeepSeek 客户端：仅用于内容审查（非流式 + tool_choice）"""

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        cfg = config if config is not None else TBRulesBreakConfig()
        self.api_key = cfg.deepseek_api_key
        self.base_url = cfg.deepseek_base_url
        self.model = cfg.deepseek_model
        self.temperature = cfg.deepseek_temperature
        self.max_tokens = cfg.deepseek_max_tokens

        self.client = None
        if not self.api_key:
            self.log.error("rules_break DeepSeek API Key 未配置，审查不可用（默认不注入）")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化 rules_break DeepSeek 客户端失败: {e}")

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
        """非流式对话：返回完整响应对象（仅用于 tool_choice 审查）"""
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
        # 工具调用强制禁用思考
        params["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            resp = self.client.chat.completions.create(**params)
            return self._clean_resp_content(resp)
        except Exception as e:
            self.log.error(f"rules_break DeepSeek 调用异常: {e}")
            return None
