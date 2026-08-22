# -*- coding: utf-8 -*-
# func/catbrain/CatValues/port/aliyun.py
# 价值观独立 Qwen（阿里云）端口（硬编码 temperature 0.7，思考强度最高）

import re
from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig


class MeowValuesAliyunLLM:
    """价值观独立 Qwen（阿里云百炼）客户端（apikey/平台可配置，参数硬编码）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = MeowCatBrainConfig()
        self.api_key = cfg.val_aliyun_api_key
        self.base_url = cfg.val_aliyun_base_url
        self.model = cfg.val_aliyun_model
        # 硬编码参数：temperature 0.7，思考强度最高
        self.temperature = cfg.values_temperature
        self.max_tokens = cfg.values_max_tokens
        self.enable_thinking = cfg.values_enable_thinking

        self.client = None
        if not self.api_key:
            self.log.error("价值观 Qwen（阿里云）API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化价值观 Qwen 客户端失败: {e}")

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
        """非流式对话，返回完整响应对象（用于价值观分析与审查）"""
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
        # 深度思考与 function calling 冲突：仅在有工具调用时禁用思考，保证 JSON 稳定输出
        params["extra_body"] = {"enable_thinking": False if tools else self.enable_thinking}
        try:
            resp = self.client.chat.completions.create(**params)
            return self._clean_resp_content(resp)
        except Exception as e:
            self.log.error(f"价值观 Qwen 调用异常: {e}")
            return None
