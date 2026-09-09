# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/port/base.py
# 绘画模型端口基类 + 工厂：统一 OpenAI 兼容接口（thinking 与 function calling 并存）
# 参考 func/llm_active/port 的写法，但配置完全独立（读取 TBFluxPainterConfig）

from typing import List, Dict, Optional


class TBFluxPainterLLMBase:
    """绘画端口统一行为：
    - chat(): 非流式，返回完整响应对象（含 message.tool_calls / message.reasoning_content）；
    - chat_stream(): 流式，返回迭代器（预留）；
    - 调用失败统一返回 None / 空迭代器，由 agent 层降级重试，不向上抛。
    """

    # 子类覆写
    provider = "base"

    def __init__(self, config):
        self.config = config
        self.client = None
        self._build_extra_body = lambda thinking: {}

    # ============ 供子类使用的公共封装 ============
    def _mk_params(self, messages, tools=None, tool_choice=None, options=None,
                   thinking=None, stream=False):
        params = {
            "model": (options or {}).get("model", self.model),
            "messages": messages,
            "stream": stream,
            "temperature": (options or {}).get("temperature", self.temperature),
            "max_tokens": (options or {}).get("max_tokens", self.max_tokens),
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        use_thinking = self.config.thinking_enabled if thinking is None else thinking
        params["extra_body"] = self._build_extra_body(use_thinking)
        return params

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             tool_choice=None, options: Optional[Dict] = None,
             enable_thinking: Optional[bool] = None):
        """非流式对话，返回完整响应对象（成功）或 None（客户端不可用/异常）"""
        if not self.client:
            return None
        try:
            params = self._mk_params(messages, tools=tools, tool_choice=tool_choice,
                                     options=options, thinking=enable_thinking, stream=False)
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"[{self.provider}] 绘画模型调用异常: {e}")
            return None

    def chat_stream(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
                    tool_choice=None, options: Optional[Dict] = None,
                    enable_thinking: Optional[bool] = None):
        """流式对话，返回 OpenAI 流式迭代器（异常时返回空迭代器）"""
        if not self.client:
            return iter([])
        try:
            params = self._mk_params(messages, tools=tools, tool_choice=tool_choice,
                                     options=options, thinking=enable_thinking, stream=True)
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"[{self.provider}] 绘画模型流式调用异常: {e}")
            return iter([])


def create_painter_llm(config):
    """工厂：按 config.llm_type 创建绘画模型端口（完全独立配置）"""
    if config.llm_type == "aliyun":
        from func.toolbox.flux_painter.port.aliyun import TBFluxPainterAliyunLLM
        return TBFluxPainterAliyunLLM(config)
    from func.toolbox.flux_painter.port.deepseek import TBFluxPainterDeepSeekLLM
    return TBFluxPainterDeepSeekLLM(config)
