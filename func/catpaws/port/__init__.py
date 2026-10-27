# -*- coding: utf-8 -*-
# func/catpaws/port/__init__.py
# catpaws 独立 LLM 端口工厂：按配置返回对应 provider 客户端
from func.catpaws.config import CWCatPawsConfig


def get_catpaws_port(config=None):
    """按 port.type 返回 catpaws 独立 LLM 端口"""
    cfg = config or CWCatPawsConfig()
    name = str(getattr(cfg, "port_type", "deepseek") or "deepseek").strip().lower()
    if name == "meowllm":
        from func.catpaws.port.meowllm import CWCatPawsMeowLLMPort
        return CWCatPawsMeowLLMPort(cfg)
    if name == "gemini":
        from func.catpaws.port.gemini import CWCatPawsGeminiPort
        return CWCatPawsGeminiPort(cfg)
    if name == "aliyun":
        from func.catpaws.port.aliyun import CWCatPawsAliyunPort
        return CWCatPawsAliyunPort(cfg)
    from func.catpaws.port.deepseek import CWCatPawsDeepSeekPort
    return CWCatPawsDeepSeekPort(cfg)
