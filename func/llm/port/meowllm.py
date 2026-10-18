# -*- coding: utf-8 -*-
# func/llm/port/meowllm.py
# MeowLLM 本地模型（OpenAI 兼容接口，支持 function calling）
#
# 与同目录的 deepseek.py 完全同构：自己读配置、自己建 OpenAI 客户端、自己拼参数。
# 本平台多几个请求字段，都在 _build_params 里就地处理：
#     * top_k / repeat_penalty 必须在**请求顶层**（放进 meowllm 子块会被 schema 静默丢弃）
#     * meowllm.thinking_level 三档：off / low / medium / high
#     * meowllm.memory_owner δ-mem 归哪个用户；**带工具时服务端会自动忽略它**
#
# ⚠ 其它模块不要 import 本文件；每个模块有自己的 `port/meowllm.py`。

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.llm.config import LLMConfig


class MeowLLMLLM:
    """MeowLLM 流式客户端（OpenAI 兼容接口）。"""

    _LEVELS = ("off", "low", "medium", "high")

    def __init__(self, config: Optional[LLMConfig] = None, *, max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None):
        self.log = DefaultLog().getLogger()
        self.config = config if config is not None else LLMConfig()
        self.base_url = self.config.meowllm_base_url
        self.model = self.config.meowllm_model
        self.temperature = float(temperature if temperature is not None
                                 else self.config.meowllm_temperature)
        self.max_tokens = int(max_tokens if max_tokens is not None
                              else self.config.meowllm_max_tokens)
        self.top_p = self.config.meowllm_top_p
        self.top_k = self.config.meowllm_top_k
        self.repeat_penalty = self.config.meowllm_repeat_penalty
        self.thinking_level = self.config.meowllm_thinking_level

        try:
            # 本地服务不鉴权，api_key 只是 OpenAI SDK 的必填占位
            self.client = OpenAI(api_key="meowllm-local", base_url=self.base_url)
            self.log.info(f"MeowLLM 客户端初始化成功，端点: {self.base_url}，模型: {self.model}")
        except Exception as e:
            self.log.error(f"初始化 MeowLLM 客户端失败: {e}")
            self.client = None

    @classmethod
    def _resolve_level(cls, enable_thinking=None, thinking_level=None) -> str:
        """把 enable_thinking(bool) / thinking_level(str) 归一成一档。"""
        if thinking_level in cls._LEVELS:
            return thinking_level
        if enable_thinking is False:
            return "off"
        if enable_thinking is True:
            return "medium"
        return ""                       # 空串 = 用配置默认值

    def _build_params(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                      options: Optional[Dict] = None, tool_choice=None,
                      enable_thinking: Optional[bool] = None,
                      thinking_level: Optional[str] = None,
                      stream: bool = True) -> Dict:
        """构建请求参数（与 deepseek 的 _build_params 同名同职责）。"""
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

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             options: Optional[Dict] = None, tool_choice=None,
             enable_thinking: Optional[bool] = None,
             thinking_level: Optional[str] = None, **kwargs):
        """非流式，返回完整响应对象；失败返回 None。"""
        if not self.client:
            self.log.error("MeowLLM 客户端不可用")
            return None
        params = self._build_params(messages, tools, options, tool_choice,
                                    enable_thinking, thinking_level, stream=False)
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"MeowLLM 调用异常: {e}")
            return None

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    options: Optional[Dict] = None, tool_choice=None,
                    enable_thinking: Optional[bool] = None,
                    thinking_level: Optional[str] = None, **kwargs):
        """流式，返回 OpenAI 流式响应迭代器；失败返回空迭代器。"""
        if not self.client:
            self.log.error("MeowLLM 客户端不可用")
            return iter([])
        params = self._build_params(messages, tools, options, tool_choice,
                                    enable_thinking, thinking_level, stream=True)
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"MeowLLM 流式调用异常: {e}")
            return iter([])
