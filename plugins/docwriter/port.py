from func.log.default_log import DefaultLog


class DocLLM:
    def __init__(self, config):
        """文档助手独立 LLM 端口（OpenAI 兼容，延迟导入避免加载期依赖）"""
        self.config = config
        self.log = DefaultLog().getLogger()
        self.last_error = ""
        self.client = None
        if not config.api_key:
            self.last_error = "未配置 LLM API Key"
            return
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        except Exception as e:
            self.last_error = f"LLM 端口初始化失败: {e}"
            self.log.exception("文档助手 LLM 端口初始化失败")

    def available(self):
        """端口是否可用"""
        return self.client is not None

    def chat(self, messages, tools=None, tool_choice=None):
        """发起对话请求，返回响应对象"""
        if not self.client:
            return None
        params = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice
        try:
            return self.client.chat.completions.create(**params)
        except Exception as e:
            self.last_error = str(e)[:200]
            self.log.exception("文档助手 LLM 调用失败")
            return None

    def chat_text(self, messages):
        """发起对话请求并返回纯文本（兜底成稿用）"""
        resp = self.chat(messages)
        if resp and getattr(resp, "choices", None):
            return str(getattr(resp.choices[0].message, "content", None) or "").strip()
        return ""
