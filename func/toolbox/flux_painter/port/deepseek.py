# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/port/deepseek.py
# 绘画模型 DeepSeek 端口（thinking 与 function calling 并存，独立 api key）


from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.flux_painter.port.base import TBFluxPainterLLMBase


class TBFluxPainterDeepSeekLLM(TBFluxPainterLLMBase):
    """DeepSeek 绘画客户端（OpenAI 兼容；thinking 由 extra_body 控制）"""

    provider = "deepseek"

    def __init__(self, config):
        super().__init__(config)
        self.log = DefaultLog().getLogger()
        conn = config.active_llm()
        self.api_key = conn["api_key"]
        self.base_url = conn["base_url"]
        self.model = conn["model"]
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens
        self.client = None
        if not self.api_key:
            self.log.error("[flux_painter] DeepSeek API Key 未配置（请在工具箱-绘画配置中填写）")
            return
        try:
            # 不设硬超时：agent 走流式 + 无数据心跳来感知运行状态，慢/长思考不会被掐断
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0)
            self.log.info(f"[flux_painter] DeepSeek 绘画客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"[flux_painter] 初始化 DeepSeek 绘画客户端失败: {e}")

    def _build_extra_body(self, thinking):
        if not thinking:
            return {"thinking": {"type": "disabled"}}
        return {"thinking": {"type": "enabled"}}
