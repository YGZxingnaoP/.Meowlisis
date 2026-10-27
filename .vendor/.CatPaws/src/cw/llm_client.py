from cw.port.base import CWPortError
from cw.port.vision import CWVisionPort
from cw.port import get_port


class CWLLMError(Exception):
    """CatPaws 模型调用异常"""


def _has_image(messages):
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False


class CWLLMClient:
    """模型客户端：带图的消息走 vision 端口，其余走主 port；两者都能用工具"""

    def __init__(self, config):
        self.config = config
        self.port = get_port(config)
        self.vision = CWVisionPort(config)

    def supports_reasoning(self):
        """是否需要在消息里回传 reasoning_content（思考模式模型）"""
        return str(getattr(self.port, "provider", "")) == "deepseek"

    def chat(self, messages, tools=None, vision=None, model=None):
        use_vision = _has_image(messages) if vision is None else bool(vision)
        try:
            if use_vision:
                return self.vision.chat(messages, tools=tools)
            return self.port.chat(messages, tools=tools, model=model)
        except CWPortError as exc:
            raise CWLLMError(str(exc))
        except Exception as exc:
            raise CWLLMError("模型调用失败：%s" % exc)

    def text(self, messages, vision=None, model=None):
        return str(self.chat(messages, tools=None, vision=vision, model=model).content or "")

    @staticmethod
    def image_part(png_bytes, detail="low"):
        return CWVisionPort.image_part(png_bytes, detail)

    @staticmethod
    def text_part(text):
        return CWVisionPort.text_part(text)
