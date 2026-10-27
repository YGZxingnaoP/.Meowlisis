from cw.port.base import CWPort, CWPortError


class CWDeepSeekPort(CWPort):
    """DeepSeek 端口（OpenAI 兼容）"""

    provider = "deepseek"
    default_base_url = "https://api.deepseek.com/v1"
    default_model = "deepseek-chat"
