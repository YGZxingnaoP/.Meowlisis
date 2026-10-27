from cw.port.aliyun import CWAliyunPort
from cw.port.base import CWPort, CWPortError
from cw.port.deepseek import CWDeepSeekPort
from cw.port.gemini import CWGeminiPort
from cw.port.meowllm import CWMeowLLMPort

CW_PORTS = {
    "deepseek": CWDeepSeekPort,
    "aliyun": CWAliyunPort,
    "gemini": CWGeminiPort,
    "meowllm": CWMeowLLMPort,
}


def get_port(config):
    """按 port.type 返回独立 LLM 端口实例"""
    name = str(getattr(config, "port_type", "deepseek") or "deepseek").strip().lower()
    return CW_PORTS.get(name, CWDeepSeekPort)(config)
