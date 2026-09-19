from func.log.default_log import DefaultLog


class EpubLLM:
    def __init__(self, config):
        """读书插件独立 LLM 端口（OpenAI 兼容，延迟导入避免加载期依赖）"""
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
            self.log.exception("读书助手 LLM 端口初始化失败")

    def available(self):
        """端口是否可用"""
        return self.client is not None

    def chat(self, messages, temperature=None, max_tokens=None):
        """发起对话请求，返回纯文本"""
        if not self.client:
            return ""
        params = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
        }
        try:
            resp = self.client.chat.completions.create(**params)
        except Exception as e:
            self.last_error = str(e)[:200]
            self.log.exception("读书助手 LLM 调用失败")
            return ""
        if resp and getattr(resp, "choices", None):
            return str(getattr(resp.choices[0].message, "content", None) or "").strip()
        return ""
