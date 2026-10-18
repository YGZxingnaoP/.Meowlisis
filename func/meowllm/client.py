# -*- coding: utf-8 -*-
# func/meowllm/client.py
"""MeowLLM 的**协议实现**：一次请求长什么样。

只做三件事，超出的都不管：
    1. 按"模块给的默认值 + 调用方覆盖"组装 OpenAI 兼容参数
    2. 把只有 MeowLLM 认识的东西放进正确的位置
       （`top_k` / `repeat_penalty` 在顶层；`thinking_level` / `memory_owner`
        在 `meowllm` 子块里）
    3. 流式时原样透传（读流异常只记日志，不把半截流伪装成正常结束）

各模块的 `port/meowllm.py` 只负责"读自己的配置 + 决定默认值"，然后把自己当
一个薄包装转发到这里 —— 这样 40 多个调用点各用各的端口，协议却只有一份。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.meowllm import config as meowllm_config
from func.meowllm import memory as meowllm_memory

_API_KEY = "meowllm"
_LEVELS = ("off", "low", "medium", "high")


class MeowLLMStreamTap:
    """流式包装：只透传，顺便把读流异常记下来。

    以前这里会悄悄把 reasoning_content 拼进 self.last_reasoning（没人读），
    读流出错时 `return` 掉 —— 上层看起来是"正常结束"。现在异常照样记日志，
    但不再维护没人消费的状态。
    """

    def __init__(self, stream, log):
        self._stream = stream
        self._log = log

    def __iter__(self):
        try:
            for chunk in self._stream:
                yield chunk
        except Exception as exc:  # noqa: BLE001
            self._log.error(f"MeowLLM 流读取异常: {exc}")
            return


class MeowLLMClient:
    """一个模块对 MeowLLM 的连接 + 默认采样参数。

    参数全部可选，由各模块的端口按自己的配置填。`label` 只用于日志前缀，
    方便在日志里分辨"到底是哪个模块在调本地模型"。
    """

    def __init__(self, *, label: str = "meowllm",
                 temperature: Optional[float] = None,
                 top_p: Optional[float] = None,
                 top_k: Optional[int] = None,
                 repeat_penalty: Optional[float] = None,
                 max_tokens: Optional[int] = None) -> None:
        self.log = DefaultLog().getLogger()
        self.label = str(label or "meowllm")
        self.base_url = meowllm_config.base_url()
        self.model = meowllm_config.model_name()
        self.temperature = float(temperature if temperature is not None
                                 else meowllm_config.gen("temperature", 0.8))
        self.top_p = float(top_p if top_p is not None
                           else meowllm_config.gen("top_p", 0.9))
        self.top_k = int(top_k if top_k is not None
                         else meowllm_config.gen("top_k", 40))
        self.repeat_penalty = float(
            repeat_penalty if repeat_penalty is not None
            else meowllm_config.gen("repeat_penalty", 1.05))
        self.max_tokens = int(max_tokens if max_tokens is not None
                              else meowllm_config.gen("talk_max_tokens", 256))
        self.thinking_level = meowllm_config.thinking_level()
        self.client = None
        try:
            self.client = OpenAI(api_key=_API_KEY, base_url=self.base_url)
            self.log.info(f"[{self.label}] MeowLLM 客户端就绪：{self.base_url} "
                          f"model={self.model}")
        except Exception as exc:  # noqa: BLE001
            self.log.error(f"[{self.label}] 初始化 MeowLLM 客户端失败: {exc}")

    # ---------------------------------------------------------------- 可用性
    @property
    def ready(self) -> bool:
        return self.client is not None

    # ---------------------------------------------------------------- 档位
    @staticmethod
    def resolve_level(enable_thinking=None, thinking_level=None) -> str:
        """把"布尔开关 / 具名档位"统一成 off|low|medium|high。"""
        if thinking_level:
            text = str(thinking_level).strip().lower()
            if text in _LEVELS:
                return text
        if enable_thinking is None:
            return ""
        return "medium" if enable_thinking else "off"

    # ---------------------------------------------------------------- 组包
    def extra_body(self, thinking: str, options: Optional[Dict] = None) -> Dict:
        """OpenAI SDK 的 extra_body 会被**平铺**进请求体顶层。

        `top_k` / `repeat_penalty` 是引擎的顶层字段 —— 放进 `meowllm` 子块里会被
        schema 当未知字段静默丢掉（老代码就是这么写的，所以项目侧一直没能真正
        覆盖这两个值）。`meowllm` 块里只放引擎认识的键。
        """
        opts = options or {}
        extra: Dict = {
            "top_k": int(opts.get("top_k", self.top_k)),
            "repeat_penalty": float(opts.get("repeat_penalty", self.repeat_penalty)),
        }
        payload: Dict = {"thinking_level": thinking or self.thinking_level}
        # 思考预算不在这里算：引擎按档位取 thinking.budgets.<level>，那是配置页里
        # 可配的唯一出处。只有调用方显式给了才透传。
        budget = opts.get("think_budget")
        if budget:
            payload["think_budget"] = int(budget)
        owner = meowllm_memory.owner_for(options=options)
        if owner:
            payload[meowllm_memory.FIELD] = owner
        extra["meowllm"] = payload
        return extra

    def params(self, messages: List[Dict], *, tools=None, tool_choice=None,
               options: Optional[Dict] = None, stream: bool = False) -> Dict:
        opts = options or {}
        body = {
            "model": opts.get("model", self.model),
            "messages": messages,
            "stream": bool(stream),
            "temperature": float(opts.get("temperature", self.temperature)),
            "top_p": float(opts.get("top_p", self.top_p)),
            "max_tokens": int(opts.get("max_tokens", self.max_tokens)),
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        return body

    # ---------------------------------------------------------------- 调用
    def chat(self, messages: List[Dict], tools=None, tool_choice=None,
             enable_thinking=None, options: Optional[Dict] = None,
             thinking_level=None, **kwargs):
        """非流式，返回完整响应对象；失败返回 None。"""
        if not self.ready:
            self.log.error(f"[{self.label}] MeowLLM 客户端不可用")
            return None
        thinking = self.resolve_level(enable_thinking, thinking_level)
        body = self.params(messages, tools=tools, tool_choice=tool_choice,
                           options=options, stream=False)
        body["extra_body"] = self.extra_body(thinking, options)
        try:
            return self.client.chat.completions.create(**body)
        except Exception as exc:  # noqa: BLE001
            self.log.error(f"[{self.label}] MeowLLM 调用异常: {exc}")
            return None

    def chat_stream(self, messages: List[Dict], tools=None, tool_choice=None,
                    options: Optional[Dict] = None, enable_thinking=None,
                    thinking_level=None, **kwargs):
        """流式；失败返回空迭代器（调用方 for 循环自然不执行）。"""
        if not self.ready:
            self.log.error(f"[{self.label}] MeowLLM 客户端不可用")
            return iter([])
        thinking = self.resolve_level(enable_thinking, thinking_level)
        body = self.params(messages, tools=tools, tool_choice=tool_choice,
                           options=options, stream=True)
        body["extra_body"] = self.extra_body(thinking, options)
        try:
            stream = self.client.chat.completions.create(**body)
        except Exception as exc:  # noqa: BLE001
            self.log.error(f"[{self.label}] MeowLLM 流式调用异常: {exc}")
            return iter([])
        return iter(MeowLLMStreamTap(stream, self.log))
