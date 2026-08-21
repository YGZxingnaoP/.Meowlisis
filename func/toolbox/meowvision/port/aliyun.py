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
        """流式对话：返回视觉模型正式回复文本（content），失败返回 None。

        QVQ 系列（qvq-plus 等）是「仅思考模型」，仅支持流式输出（stream=True）；
        非流式调用会返回空 content。因此这里统一走流式，收集 reasoning_content
        与 content，最终只返回正式回复 content。
        """
        if not self.client:
            self.log.error("MeowVision 阿里云视觉客户端不可用")
            return None
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if self.top_p is not None:
            params["top_p"] = self.top_p

        reasoning_len = 0
        answer_parts = []
        try:
            stream = self.client.chat.completions.create(**params)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "reasoning_content", None):
                    reasoning_len += len(delta.reasoning_content)
                if getattr(delta, "content", None):
                    answer_parts.append(delta.content)
        except Exception as e:
            self.log.error(f"MeowVision 阿里云视觉调用异常: {e}")
            return None

        answer = "".join(answer_parts).strip()
        if not answer:
            self.log.warning(
                f"MeowVision 视觉模型 content 为空：reasoning={reasoning_len} 字，"
                f"max_tokens={self.max_tokens}（QVQ 仅思考模型，若 reasoning 已满可能是 max_tokens 不足）"
            )
            return None
        return answer
