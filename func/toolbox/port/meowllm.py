# -*- coding: utf-8 -*-
# func/toolbox/port/meowllm.py
# Toolbox 独立 MeowLLM 端口（本地子服务，OpenAI 兼容）
#
# 与同目录的 deepseek.py 完全同构：自己读配置、自己建 OpenAI 客户端、自己拼参数。
# 本平台多几个请求字段，都在 _build_params 里就地处理：
#     * top_k / repeat_penalty 必须在**请求顶层**（放进 meowllm 子块会被 schema 静默丢弃）
#     * meowllm.thinking_level 三档：off / low / medium / high
#     * meowllm.memory_owner δ-mem 归哪个用户；**带工具时服务端会自动忽略**，
#       所以这里不需要为 δ-mem 写任何特判。

import os
from typing import Dict, List, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.config import TBoxConfig


#: 本地子服务端点。可用环境变量覆盖（云端/换端口时不用改代码）。
DEFAULT_BASE_URL = os.environ.get("MEOWLLM_BASE_URL", "http://127.0.0.1:18100/meowllm/v1")
_LEVELS = ("off", "low", "medium", "high")


def _pick(cfg, *names):
    """按顺序取第一个非 None 的属性（各模块配置字段名不完全统一）。"""
    for name in names:
        value = getattr(cfg, name, None)
        if value is not None:
            return value
    return None


class TBoxMeowLLM:
    """Toolbox 独立 MeowLLM 客户端（父级 toolcalls / NapCat 复用，可注入外部 config）"""

    provider = "meowllm"

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        self.config = cfg = config if config is not None else TBoxConfig()
        self.base_url = _pick(cfg, "meowllm_base_url") or DEFAULT_BASE_URL
        self.model = _pick(cfg, "meowllm_model") or "meowllm-local"
        self.temperature = float(_pick(cfg, "meowllm_temperature", "temperature") or 0.8)
        self.max_tokens = int(_pick(cfg, "meowllm_max_tokens", "max_tokens") or 2048)
        self.top_p = float(_pick(cfg, "meowllm_top_p", "top_p") or 0.9)
        self.top_k = int(_pick(cfg, "meowllm_top_k") or 40)
        self.repeat_penalty = float(_pick(cfg, "meowllm_repeat_penalty") or 1.05)
        self.thinking_level = str(_pick(cfg, "meowllm_thinking_level") or "off")

        try:
            # 本地服务不鉴权，api_key 只是 OpenAI SDK 的必填占位
            self.client = OpenAI(api_key="meowllm-local", base_url=self.base_url)
            self.log.info(f"[toolbox] MeowLLM 客户端初始化成功，端点: {self.base_url}")
        except Exception as e:
            self.log.error(f"[toolbox] 初始化 MeowLLM 客户端失败: {e}")
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

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, options: Optional[Dict] = None,
             enable_thinking=None, thinking_level=None, **kwargs):
        if not self.client:
            self.log.error("[toolbox] MeowLLM 客户端不可用")
            return None
        params = self._build_params(messages, tools, options, tool_choice,
                                    enable_thinking, thinking_level, stream=False)
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"[toolbox] MeowLLM 调用异常: {e}")
            return None

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    enable_thinking=None, thinking_level=None, **kwargs):
        if not self.client:
            self.log.error("[toolbox] MeowLLM 客户端不可用")
            return iter([])
        params = self._build_params(messages, tools, options, tool_choice,
                                    enable_thinking, thinking_level, stream=True)
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"[toolbox] MeowLLM 流式调用异常: {e}")
            return iter([])


# 兼容历史调用名（老代码里写的是 MeowLLMLLM）
MeowLLMLLM = TBoxMeowLLM
