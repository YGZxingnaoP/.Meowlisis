# -*- coding: utf-8 -*-
# func/toolbox/svg_painter/port/aliyun.py
# 绘画模型阿里云百炼端口（thinking 与 function calling 并存，独立 api key）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.svg_painter.port.base import TBSvgPainterLLMBase


class TBSvgPainterAliyunLLM(TBSvgPainterLLMBase):
    """阿里云百炼（Qwen）绘画客户端（OpenAI 兼容；enable_thinking 走 extra_body）"""

    provider = "aliyun"

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
            self.log.error("[svg_painter] 阿里云 API Key 未配置（请在工具箱-绘画配置中填写）")
            return
        try:
            # 不设硬超时：agent 走流式 + 无数据心跳来感知运行状态，慢/长思考不会被掐断
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0)
            self.log.info(f"[svg_painter] 阿里云绘画客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"[svg_painter] 初始化阿里云绘画客户端失败: {e}")

    def _build_extra_body(self, thinking):
        # 阿里云 DashScope OpenAI 兼容：enable_thinking 放 extra_body
        return {"enable_thinking": bool(thinking)}
