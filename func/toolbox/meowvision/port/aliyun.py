# -*- coding: utf-8 -*-
# func/toolbox/meowvision/port/aliyun.py
# MeowVision 视觉理解模型端口（阿里云百炼 / MaaS，OpenAI 兼容，非流式）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.toolbox.meowvision.config import TBVisionConfig


class TBVisionAliyunLLM:
    """MeowVision 视觉理解客户端（qvq 系列多模态，仅阿里云平台）

    - 非流式调用，直接返回模型看过图片后的正式回复内容（content）。
    - qvq 系列思考过程位于 message.reasoning_content，正式回答位于 message.content，
      此处仅取 content，思考内容由上层按需忽略。
    """

    def __init__(self, config: Optional[TBVisionConfig] = None):
        self.log = DefaultLog().getLogger()
        cfg = config if config is not None else TBVisionConfig()
        self.api_key = cfg.api_key
        self.base_url = cfg.base_url
        self.model = cfg.model
        self.max_tokens = cfg.max_tokens
        self.temperature = cfg.temperature
        self.top_p = cfg.top_p

        self.client = None
        if not self.api_key:
            self.log.error("MeowVision 阿里云视觉 API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.log.info(f"MeowVision 阿里云视觉客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"初始化 MeowVision 阿里云视觉客户端失败: {e}")

    def chat(self, messages: List[Dict]) -> Optional[str]:
        """非流式对话：返回视觉模型正式回复文本（content），失败返回 None"""
        if not self.client:
            self.log.error("MeowVision 阿里云视觉客户端不可用")
            return None
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.top_p is not None:
            params["top_p"] = self.top_p
        try:
            resp = self.client.chat.completions.create(**params)
            if not resp or not getattr(resp, "choices", None):
                return None
            msg = resp.choices[0].message
            content = getattr(msg, "content", None)
            # 仅接受文本内容；非 str（如多模态返回 list）时返回 None，避免上游拿到非预期类型
            if isinstance(content, str) and content.strip():
                return content
            return None
        except Exception as e:
            self.log.error(f"MeowVision 阿里云视觉调用异常: {e}")
            return None
