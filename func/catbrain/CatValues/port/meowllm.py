# -*- coding: utf-8 -*-
# func/catbrain/CatValues/port/meowllm.py
# 价值观独立 MeowLLM 端口（本地子服务，OpenAI 兼容）
#
# 与同目录的 deepseek.py 完全同构：自己读配置、自己建 OpenAI 客户端、自己拼参数。

import os
import re
from typing import Dict, List, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig


DEFAULT_BASE_URL = os.environ.get("MEOWLLM_BASE_URL", "http://127.0.0.1:18100/meowllm/v1")
_LEVELS = ("off", "low", "medium", "high")


class MeowValuesMeowLLM:
    """价值观 MeowLLM 客户端"""

    provider = "meowllm"

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        self.config = cfg = config if config is not None else MeowCatBrainConfig()
        self.base_url = getattr(cfg, "meowllm_base_url", None) or DEFAULT_BASE_URL
        self.model = getattr(cfg, "meowllm_model", None) or "meowllm-local"
        self.temperature = float(getattr(cfg, "values_temperature", None) or 0.8)
        self.max_tokens = int(getattr(cfg, "values_max_tokens", None) or 2048)
        self.top_p = float(getattr(cfg, "top_p", None) or 0.9)
        self.top_k = int(getattr(cfg, "meowllm_top_k", None) or 40)
        self.repeat_penalty = float(getattr(cfg, "meowllm_repeat_penalty", None) or 1.05)
        self.thinking_level = str(getattr(cfg, "meowllm_thinking_level", None) or "off")

        try:
            self.client = OpenAI(api_key="meowllm-local", base_url=self.base_url)
            self.log.info(f"[cat_values] MeowLLM 客户端初始化成功，端点: {self.base_url}")
        except Exception as e:
            self.log.error(f"[cat_values] 初始化 MeowLLM 客户端失败: {e}")
            self.client = None

    @staticmethod
    def _resolve_level(enable_thinking=None, thinking_level=None) -> str:
        if thinking_level in _LEVELS:
            return thinking_level
        if enable_thinking is False:
            return "off"
        if enable_thinking is True:
            return "medium"
        return ""

    def _build_params(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                      options: Optional[Dict] = None, tool_choice=None,
                      enable_thinking: Optional[bool] = None,
                      thinking_level: Optional[str] = None,
                      stream: bool = True) -> Dict:
        options = options or {}
        params = {
            "model": options.get("model", self.model),
            "messages": messages,
            "stream": bool(stream),
            "temperature": options.get("temperature", self.temperature),
            "top_p": options.get("top_p", self.top_p),
            "max_tokens": options.get("max_tokens", self.max_tokens),
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice

        block: Dict = {}
        level = self._resolve_level(enable_thinking, thinking_level) or self.thinking_level
        if level:
            block["thinking_level"] = level
        owner = options.get("memory_owner")
        if owner:
            block["memory_owner"] = owner

        params["extra_body"] = {
            "top_k": int(options.get("top_k", self.top_k)),
            "repeat_penalty": float(options.get("repeat_penalty", self.repeat_penalty)),
            "meowllm": block,
        }
        return params

    @staticmethod
    def _clean_resp_content(resp):
        """去除响应 content 中的全角方括号【】及其内容（与其它摘要端口一致）"""
        try:
            if resp and getattr(resp, "choices", None):
                content = getattr(resp.choices[0].message, "content", None)
                if isinstance(content, str) and content:
                    resp.choices[0].message.content = re.sub(
                        r"【[^】]*】", "", content).strip()
        except Exception:
            pass
        return resp

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, options: Optional[Dict] = None,
             enable_thinking=None, thinking_level=None, **kwargs):
        if not self.client:
            self.log.error("[cat_values] MeowLLM 客户端不可用")
            return None
        params = self._build_params(messages, tools, options, tool_choice,
                                    enable_thinking, thinking_level, stream=False)
        try:
            return self._clean_resp_content(
                self.client.chat.completions.create(**params))
        except Exception as e:
            self.log.error(f"[cat_values] MeowLLM 调用异常: {e}")
            return None

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    enable_thinking=None, thinking_level=None, **kwargs):
        if not self.client:
            self.log.error("[cat_values] MeowLLM 客户端不可用")
            return iter([])
        params = self._build_params(messages, tools, options, tool_choice,
                                    enable_thinking, thinking_level, stream=True)
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"[cat_values] MeowLLM 流式调用异常: {e}")
            return iter([])


MeowLLMLLM = MeowValuesMeowLLM
