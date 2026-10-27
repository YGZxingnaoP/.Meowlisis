import base64

from openai import OpenAI

from cw.port.base import clean_content


class CWVisionPort:
    """看图端口：独立 base_url/api_key/model，未配置时回落到主端口"""

    def __init__(self, config):
        self.config = config
        self.base_url = str(getattr(config, "vision_base_url", "") or config.llm_base_url)
        self.api_key = str(getattr(config, "vision_api_key", "") or config.llm_api_key)
        self.model = str(getattr(config, "vision_model", "") or config.llm_model)
        self.max_edge = int(getattr(config, "vision_max_edge", 1024) or 1024)
        self._client = None

    def client(self):
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("catpaws vision 未配置 api_key")
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url,
                                  timeout=120, max_retries=1)
        return self._client

    def chat(self, messages, tools=None, tool_choice="auto"):
        params = {"model": self.model, "messages": messages}
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice or "auto"
        response = self.client().chat.completions.create(**params)
        if not response.choices:
            raise RuntimeError("vision 没有返回结果")
        return clean_content(response.choices[0].message)

    def text(self, messages):
        return str(self.chat(messages).content or "")

    @staticmethod
    def image_part(png_bytes, detail="low"):
        encoded = base64.b64encode(png_bytes).decode("ascii")
        return {"type": "image_url",
                "image_url": {"url": "data:image/png;base64," + encoded, "detail": detail}}

    @staticmethod
    def text_part(text):
        return {"type": "text", "text": str(text)}
