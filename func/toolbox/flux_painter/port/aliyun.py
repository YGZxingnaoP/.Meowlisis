# -*- coding: utf-8 -*-

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.flux_painter.port.base import TBFluxPainterLLMBase

class TBFluxPainterAliyunLLM(TBFluxPainterLLMBase):
    """阿里云百炼（Qwen）绘画客户端（OpenAI 兼容；enable_thinking 走 extra_body）"""

    provider = "aliyun"

    def __init__(self, config):
        """初始化。"""
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
            self.log.error("[flux_painter] 阿里云 API Key 未配置（请在工具箱-绘画配置中填写）")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0)
            self.log.info(f"[flux_painter] 阿里云绘画客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"[flux_painter] 初始化阿里云绘画客户端失败: {e}")

    def _build_extra_body(self, thinking):
        """构造思考开关的 extra_body。"""
        return {"enable_thinking": bool(thinking)}
