from cw.port.base import CWPort, CWPortError


class CWGeminiPort(CWPort):
    """Gemini 端口（OpenAI 兼容网关）"""

    provider = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    default_model = "gemini-3.6-flash"
