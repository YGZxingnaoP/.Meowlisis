import re

from openai import OpenAI


class CWPortError(Exception):
    """CatPaws 独立 LLM 端口异常"""


def clean_content(message):
    try:
        content = getattr(message, "content", None)
        if isinstance(content, str) and content:
            message.content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
    except Exception:
        pass
    return message


class CWPort:
    """OpenAI 兼容端口基类：自己读配置、自己建客户端、自己拼参数"""

    provider = "deepseek"
    default_base_url = "https://api.deepseek.com/v1"
    default_model = "deepseek-chat"

    def __init__(self, config):
        self.config = config
        self.options = dict(getattr(config, "port_options", {}) or {})
        self.base_url = str(self.options.get("base_url") or self.default_base_url)
        self.api_key = str(self.options.get("api_key") or "")
        self.model = str(self.options.get("model") or self.default_model)
        self.temperature = float(self.options.get("temperature") or 0.6)
        self.max_tokens = int(self.options.get("max_tokens") or 4096)
        self._client = None

    def client(self):
        if self._client is None:
            if not self.api_key and not self.anonymous():
                raise CWPortError("catpaws port（%s）未配置 api_key" % self.provider)
            self._client = OpenAI(api_key=self.api_key or "catpaws-local",
                                  base_url=self.base_url, timeout=120, max_retries=1)
        return self._client

    def anonymous(self):
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
        params = self.build_params(messages, tools, tool_choice, model, temperature, max_tokens)
        try:
            response = self.client().chat.completions.create(**params)
        except CWPortError:
            raise
        except Exception as exc:
            raise CWPortError("catpaws port（%s）调用失败：%s" % (self.provider, exc))
        if not response.choices:
            raise CWPortError("catpaws port（%s）没有返回结果" % self.provider)
        return clean_content(response.choices[0].message)

    def text(self, messages, **kwargs):
        return str(self.chat(messages, tools=None, **kwargs).content or "")
