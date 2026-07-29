# -*- coding: utf-8 -*-
"""
智谱 AI (BigModel) 接口封装
支持流式和非流式调用，兼容 OpenAI API 格式
"""
import requests
import json
from typing import Generator, Dict, Any, Optional
from func.log.default_log import DefaultLog
from func.config.default_config import defaultConfig
from func.tools.singleton_mode import singleton


@singleton
class BigModel:
    log = DefaultLog().getLogger()
    config = defaultConfig().get_config()

    def __init__(self):
        bigmodel_cfg = self.config.get("llm", {}).get("bigmodel", {})
        self.api_key = bigmodel_cfg.get("api_key", "")
        self.base_url = bigmodel_cfg.get("base_url", "https://open.bigmodel.cn/api/paas/v4")
        self.model = bigmodel_cfg.get("model", "glm-4.7-flash")
        self.temperature = bigmodel_cfg.get("temperature", 0.7)
        self.max_tokens = bigmodel_cfg.get("max_tokens", 1024)
        self.stream = bigmodel_cfg.get("stream", True)  # 默认流式

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def generate_stream(self, messages: list, options: Optional[Dict[str, Any]] = None) -> Generator[str, None, None]:
        if not self.api_key:
            self.log.error("智谱 API Key 未配置")
            yield "喵呜的 API Key 没配置好，快去找主人！"
            return

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": options.get("temperature", self.temperature) if options else self.temperature,
            "max_tokens": options.get("max_tokens", self.max_tokens) if options else self.max_tokens,
            "stream": True,
            "thinking": {"type": "disabled"}
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload, stream=True, timeout=120)
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8').strip()
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            self.log.warning(f"解析智谱流式响应失败: {data}")
        except Exception as e:
            self.log.exception("智谱流式调用异常")
            yield "喵呜遇到问题了，稍后再试试吧。"

    def generate(self, messages: list, options: Optional[Dict[str, Any]] = None) -> str:
        """
        非流式生成回复
        :param messages: OpenAI 格式的消息列表
        :param options: 额外参数
        :return: 完整回复文本
        """
        if not self.api_key:
            self.log.error("智谱 API Key 未配置")
            return "喵呜的 API Key 没配置好，快去找主人！"

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": options.get("temperature", self.temperature) if options else self.temperature,
            "max_tokens": options.get("max_tokens", self.max_tokens) if options else self.max_tokens,
            "stream": False
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            self.log.exception("智谱非流式调用异常")
            return "喵呜出了点小差错，请稍后再试。"