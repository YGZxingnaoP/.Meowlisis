# -*- coding: utf-8 -*-

from typing import Dict, List, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.llm import meowllm_config

_API_KEY = "meowllm"
_LEVELS = ("off", "low", "medium", "high")


class MeowLLMLLM:

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        self.client = None
        self.base_url = meowllm_config.base_url()
        self.model = meowllm_config.model_name()
        self.temperature = float(meowllm_config.gen("temperature", 0.8))
        self.top_p = float(meowllm_config.gen("top_p", 0.9))
        self.top_k = int(meowllm_config.gen("top_k", 40))
        self.repeat_penalty = float(meowllm_config.gen("repeat_penalty", 1.05))
        self.talk_max_tokens = int(meowllm_config.gen("talk_max_tokens", 256))
        self.think_max_tokens = int(meowllm_config.gen("think_max_tokens", 1024))
        self.thinking_level = meowllm_config.thinking_level()
        self.context_tokens = meowllm_config.conversation_tokens()
        self.last_reasoning = ""
        try:
            self.client = OpenAI(api_key=_API_KEY, base_url=self.base_url)
            self.log.info(f"MeowLLM 客户端初始化成功，端点: {self.base_url}，模型: {self.model}")
        except Exception as e:
            self.log.error(f"初始化 MeowLLM 客户端失败: {e}")

    @staticmethod
    def _level(enable_thinking=None, thinking_level=None) -> str:
        if thinking_level:
            text = str(thinking_level).strip().lower()
            if text in _LEVELS:
                return text
        if enable_thinking is None:
            return ""
        return "medium" if enable_thinking else "off"

    def _extra_body(self, thinking: str, options: Optional[Dict]) -> Dict:
        body = {
            "top_k": int((options or {}).get("top_k", self.top_k)),
            "repeat_penalty": float((options or {}).get("repeat_penalty", self.repeat_penalty)),
        }
        level = thinking or self.thinking_level
        payload = {"thinking_level": level}
        if level != "off":
            budget = (options or {}).get("think_budget")
            payload["think_budget"] = int(budget) if budget else self.think_max_tokens
        body["meowllm"] = payload
        return body

    def _params(self, messages: List[Dict], tools: Optional[List[Dict]],
                tool_choice, options: Optional[Dict], stream: bool) -> Dict:
        opts = options or {}
        params = {
            "model": opts.get("model", self.model),
            "messages": messages,
            "stream": bool(stream),
            "temperature": float(opts.get("temperature", self.temperature)),
            "top_p": float(opts.get("top_p", self.top_p)),
            "max_tokens": int(opts.get("max_tokens", self.talk_max_tokens)),
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        return params

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, enable_thinking=None,
             options: Optional[Dict] = None, thinking_level=None, **kwargs):
        if not self.client:
            self.log.error("MeowLLM 客户端不可用")
            return None
        thinking = self._level(enable_thinking, thinking_level)
        params = self._params(messages, tools, tool_choice, options, stream=False)
        params["extra_body"] = self._extra_body(thinking, options)
        try:
            resp = self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"MeowLLM 调用异常: {e}")
            return None
        try:
            message = resp.choices[0].message if getattr(resp, "choices", None) else None
            self.last_reasoning = getattr(message, "reasoning_content", "") or ""
        except Exception:
            self.last_reasoning = ""
        return resp

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    enable_thinking=None, thinking_level=None, **kwargs):
        if not self.client:
            self.log.error("MeowLLM 客户端不可用")
            return iter([])
        thinking = self._level(enable_thinking, thinking_level)
        self.last_reasoning = ""
        params = self._params(messages, tools, tool_choice, options, stream=True)
        params["extra_body"] = self._extra_body(thinking, options)
        try:
            stream = self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"MeowLLM 流式调用异常: {e}")
            return iter([])
        return self._tap(stream)

    def _tap(self, stream):
        try:
            for chunk in stream:
                try:
                    if not getattr(chunk, "choices", None):
                        continue
                    delta = chunk.choices[0].delta
                    piece = getattr(delta, "reasoning_content", None)
                    if piece:
                        self.last_reasoning += piece
                except (IndexError, AttributeError):
                    pass
                yield chunk
        except Exception as e:
            self.log.error(f"MeowLLM 流读取异常: {e}")
            return
