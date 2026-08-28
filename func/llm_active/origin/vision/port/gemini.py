# -*- coding: utf-8 -*-
# func/llm_active/origin/vision/port/gemini.py
# 主动回复视觉理解模型端口（Google Gemini，OpenAI 兼容，流式）

from typing import List, Dict, Optional

from openai import OpenAI

from func.log.default_log import DefaultLog
from func.llm_active.origin.vision.config import AutoVisionConfig


class AutoVisionGeminiLLM:
    """主动回复视觉理解客户端（多模态，Gemini，独立 api）

    - 流式调用，收集正式回复 content；思考过程（reasoning_content）忽略。
    - 结构照搬 meowvision 的 port，但配置完全独立。
    """

    def __init__(self, config: Optional[AutoVisionConfig] = None):
        self.log = DefaultLog().getLogger()
        cfg = config if config is not None else AutoVisionConfig()
        self.api_key = cfg.gemini_api_key
        self.base_url = cfg.gemini_base_url
        self.model = cfg.gemini_model
        self.max_tokens = cfg.gemini_max_tokens
        self.temperature = cfg.gemini_temperature
        self.top_p = cfg.gemini_top_p

        self.client = None
        if not self.api_key:
            self.log.error("主动回复视觉 Gemini API Key 未配置")
            return
        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.log.info(f"主动回复视觉 Gemini 客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"初始化主动回复视觉 Gemini 客户端失败: {e}")

    def chat(self, messages: List[Dict]) -> Optional[str]:
        """流式对话：返回视觉模型正式回复文本（content），失败返回 None。"""
        if not self.client:
            self.log.error("主动回复视觉 Gemini 客户端不可用")
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
            self.log.error(f"主动回复视觉 Gemini 调用异常: {e}")
            return None

        answer = "".join(answer_parts).strip()
        if not answer:
            self.log.warning(
                f"主动回复视觉 Gemini content 为空：reasoning={reasoning_len} 字，"
                f"max_tokens={self.max_tokens}（若 reasoning 已满可能是 max_tokens 不足）"
            )
            return None
        return answer
