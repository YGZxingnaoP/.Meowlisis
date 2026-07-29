import json
from typing import List, Dict, Generator, Optional
from openai import OpenAI

from func.log.default_log import DefaultLog
from func.config.default_config import defaultConfig


class DeepSeekLLM:
    """DeepSeek 流式调用（基于 OpenAI 兼容接口）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        config = defaultConfig().get_config()
        deepseek_cfg = config.get('llm', {}).get('deepseek', {})
        self.api_key = deepseek_cfg.get('api_key', '')
        self.base_url = deepseek_cfg.get('base_url', 'https://api.deepseek.com/v1')
        self.model = deepseek_cfg.get('model', 'deepseek-chat')
        self.temperature = deepseek_cfg.get('temperature', 0.7)
        self.max_tokens = deepseek_cfg.get('max_tokens', 1024)
        self.top_p = deepseek_cfg.get('top_p', 0.9)
        self.stream = deepseek_cfg.get('stream', True)  # 默认开启流式

        if not self.api_key:
            self.log.error("DeepSeek API Key 未配置")
            self.client = None
            return

        try:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
            self.log.info(f"DeepSeek 客户端初始化成功，模型: {self.model}")
        except Exception as e:
            self.log.error(f"初始化 DeepSeek 客户端失败: {e}")
            self.client = None

    def generate_stream(self, messages: List[Dict[str, str]], options: Optional[Dict] = None) -> Generator[str, None, None]:
        """流式生成，默认禁用思考模式"""
        if not self.client:
            self.log.error("DeepSeek 客户端不可用")
            yield ""
            return

        # 默认禁用思考模式
        extra_body = {"thinking": {"type": "disabled"}}
        if options and "extra_body" in options:
            extra_body = options["extra_body"]  # 允许外部覆盖

        params = {
            "model": options.get("model", self.model) if options else self.model,
            "messages": messages,
            "stream": True,
            "temperature": options.get("temperature", self.temperature) if options else self.temperature,
            "max_tokens": options.get("max_tokens", self.max_tokens) if options else self.max_tokens,
            "top_p": options.get("top_p", self.top_p) if options else self.top_p,
            "extra_body": extra_body,
            "stream_options": {"include_usage": True}
        }

        try:
            response = self.client.chat.completions.create(**params)
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            self.log.error(f"DeepSeek 流式调用异常: {e}")
            yield ""

    def generate(self, messages: List[Dict[str, str]], options: Optional[Dict] = None) -> str:
        """非流式生成，默认禁用思考模式"""
        if not self.client:
            return ""

        extra_body = {"thinking": {"type": "disabled"}}
        if options and "extra_body" in options:
            extra_body = options["extra_body"]

        params = {
            "model": options.get("model", self.model) if options else self.model,
            "messages": messages,
            "stream": False,
            "temperature": options.get("temperature", self.temperature) if options else self.temperature,
            "max_tokens": options.get("max_tokens", self.max_tokens) if options else self.max_tokens,
            "top_p": options.get("top_p", self.top_p) if options else self.top_p,
            "extra_body": extra_body,
        }

        try:
            response = self.client.chat.completions.create(**params)
            return response.choices[0].message.content
        except Exception as e:
            self.log.error(f"DeepSeek 非流式调用异常: {e}")
            return ""