from func.log.default_log import DefaultLog
from func.psyche.config import MeowPsycheConfig


class MeowPsycheDeepSeekLLM:
    def __init__(self):
        """心理模块 DeepSeek 客户端"""
        self.log = DefaultLog().getLogger()
        cfg = MeowPsycheConfig()
        self.api_key = cfg.deepseek_api_key
        self.base_url = cfg.deepseek_base_url
        self.model = cfg.deepseek_model
        self.max_tokens = cfg.max_tokens
        self.temperature = cfg.temperature
        self.client = None
        if not self.api_key:
            self.log.error("心理模块 DeepSeek API Key 未配置")
            return
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception as e:
            self.log.error(f"初始化心理模块 DeepSeek 客户端失败: {e}")

    def chat(self, messages, tools=None, tool_choice=None):
        """非流式对话，返回完整响应对象"""
        if not self.client:
            return None
        params = {"model": self.model, "messages": messages,
                  "max_tokens": self.max_tokens, "temperature": self.temperature}
        if tools:
            params["tools"] = tools
            # DeepSeek 在 thinking 模式下不接受强制工具调用，会直接 400；用工具时关掉
            params["extra_body"] = {"thinking": {"type": "disabled"}}
        if tool_choice:
            params["tool_choice"] = tool_choice
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.log.error(f"心理模块 DeepSeek 调用异常: {e}")
            return None
