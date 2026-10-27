from cw.port.base import CWPort, CWPortError


class CWAliyunPort(CWPort):
    """阿里云 Qwen 端口（OpenAI 兼容）"""

    provider = "aliyun"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_model = "qwen-plus"
