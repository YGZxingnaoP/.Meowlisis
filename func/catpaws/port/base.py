# -*- coding: utf-8 -*-
# func/catpaws/port/base.py
# catpaws 独立 LLM 端口基类（OpenAI 兼容，apikey 与参数完全独立于主项目）
import re

from openai import OpenAI

from func.catpaws.config import CWCatPawsConfig
from func.log.default_log import DefaultLog


class CWPortError(Exception):
    """catpaws 端口调用异常"""


def clean_content(message):
    try:
        content = getattr(message, "content", None)
        if isinstance(content, str) and content:
            message.content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
    except Exception:
        pass
    return message


class CWCatPawsPort:
    """单个 provider 的客户端：自己读配置、自己建客户端、自己拼参数"""

    provider = "deepseek"
    default_base_url = "https://api.deepseek.com/v1"
    default_model = "deepseek-chat"

    def __init__(self, config=None):
        self.log = DefaultLog().getLogger()
        cfg = config or CWCatPawsConfig()
        self.options = dict(getattr(cfg, "port_options", {}) or {})
        self.base_url = str(self.options.get("base_url") or self.default_base_url)
        self.api_key = str(self.options.get("api_key") or "")
        self.model = str(self.options.get("model") or self.default_model)
        self.temperature = float(self.options.get("temperature") or 0.5)
        self.max_tokens = int(self.options.get("max_tokens") or 2048)
        self.client = None
        if not self.api_key and not self.anonymous():
            self.log.error("catpaws port（%s）未配置 api_key" % self.provider)
            return
        try:
            self.client = OpenAI(api_key=self.api_key or "catpaws-local",
                                 base_url=self.base_url, timeout=60, max_retries=1)
        except Exception as exc:
            self.log.error("初始化 catpaws port（%s）失败：%s" % (self.provider, exc))
            self.client = None

    def anonymous(self):
        """本地端口不需要 api_key"""
        return False

    def build_params(self, messages, tools=None, tool_choice="auto", model=None,
                     temperature=None, max_tokens=None):
        params = {
            "model": model or self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice or "auto"
        return params

    def chat(self, messages, tools=None, tool_choice="auto", model=None,
             temperature=None, max_tokens=None):
        if not self.client:
            raise CWPortError("catpaws port（%s）客户端不可用" % self.provider)
        params = self.build_params(messages, tools, tool_choice, model, temperature, max_tokens)
        try:
            response = self.client.chat.completions.create(**params)
        except Exception as exc:
            raise CWPortError("catpaws port（%s）调用失败：%s" % (self.provider, exc))
        if not response.choices:
            raise CWPortError("catpaws port（%s）没有返回结果" % self.provider)
        return clean_content(response.choices[0].message)

    def text(self, messages, **kwargs):
        return str(self.chat(messages, tools=None, **kwargs).content or "")
