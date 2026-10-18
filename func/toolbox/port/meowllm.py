# -*- coding: utf-8 -*-
# func/toolbox/port/meowllm.py
# Toolbox 独立 MeowLLM 端口（本地子服务，OpenAI 兼容）
#
# 协议（端点 / thinking_level / top_k 位置 / δ-mem owner）在 func/meowllm/ 里，
# 那是基础设施；本文件只做"读 Toolbox 自己的配置 + 转发"，不 import 任何模块的 port。

from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.meowllm import MeowLLMClient
from func.toolbox.config import TBoxConfig


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
        self.engine = MeowLLMClient(
            label="toolbox",
            temperature=_pick(cfg, "meowllm_temperature", "temperature"),
            max_tokens=_pick(cfg, "meowllm_max_tokens", "max_tokens"),
        )
        self.client = self.engine.client
        self.base_url = self.engine.base_url
        self.model = self.engine.model
        self.temperature = self.engine.temperature
        self.max_tokens = self.engine.max_tokens
        self.top_p = self.engine.top_p

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, options: Optional[Dict] = None,
             enable_thinking=None, **kwargs):
        return self.engine.chat(messages, tools=tools, tool_choice=tool_choice,
                                options=options, enable_thinking=enable_thinking)

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    enable_thinking=None, **kwargs):
        return self.engine.chat_stream(messages, tools=tools,
                                       tool_choice=tool_choice, options=options,
                                       enable_thinking=enable_thinking)


# 兼容历史调用名（老代码里写的是 MeowLLMLLM）
MeowLLMLLM = TBoxMeowLLM
