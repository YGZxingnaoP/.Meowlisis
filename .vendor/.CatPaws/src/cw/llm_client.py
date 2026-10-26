import base64

from openai import OpenAI


class CWLLMError(Exception):
    pass


class CWLLMClient:
    def __init__(self, config):
        self.config = config
        self._clients = {}

    def _client(self, vision=False):
        base_url = self.config.vision_base_url if vision else self.config.llm_base_url
        api_key = self.config.vision_api_key if vision else self.config.llm_api_key
        if vision and not api_key:
            api_key = self.config.llm_api_key
        if not api_key:
            raise CWLLMError("未配置 catpaws.llm.api_key")
        key = (base_url, api_key)
        if key not in self._clients:
            self._clients[key] = OpenAI(base_url=base_url, api_key=api_key, timeout=90, max_retries=1)
        return self._clients[key]

    def chat(self, messages, tools=None, vision=False, model=None):
        client = self._client(vision=vision)
        name = model or (self.config.vision_model if vision else self.config.llm_model)
        kwargs = {
            "model": name,
            "messages": messages,
            "temperature": self.config.llm_temperature,
            "max_tokens": self.config.llm_max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise CWLLMError("模型调用失败：%s" % exc)
        if not response.choices:
            raise CWLLMError("模型没有返回结果")
        return response.choices[0].message

    def text(self, messages, vision=False, model=None):
        message = self.chat(messages, tools=None, vision=vision, model=model)
        return str(message.content or "")

    @staticmethod
    def image_part(png_bytes, detail="low"):
        encoded = base64.b64encode(png_bytes).decode("ascii")
        return {"type": "image_url",
                "image_url": {"url": "data:image/png;base64," + encoded, "detail": detail}}

    @staticmethod
    def text_part(text):
        return {"type": "text", "text": str(text)}
