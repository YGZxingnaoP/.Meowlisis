# -*- coding: utf-8 -*-
# func/toolbox/port/__init__.py
# Toolbox 独立 LLM 端口（deepseek / qwen-aliyun / gemini / meowllm，功能独立于其它模块）


def create_toolbox_llm(config=None):
    """按 toolbox 配置创建父级 LLM 端口（未知类型回落 deepseek）"""
    from func.toolbox.config import TBoxConfig
    cfg = config if config is not None else TBoxConfig()
    kind = str(getattr(cfg, "llm_type", "deepseek") or "deepseek")
    if kind == "meowllm":
        from func.toolbox.port.meowllm import TBoxMeowLLM
        return TBoxMeowLLM(cfg)
    if kind == "gemini":
        from func.toolbox.port.gemini import TBoxGeminiLLM
        return TBoxGeminiLLM(cfg)
    if kind == "aliyun":
        from func.toolbox.port.aliyun import TBoxAliyunLLM
        return TBoxAliyunLLM(cfg)
    from func.toolbox.port.deepseek import TBoxDeepSeekLLM
    return TBoxDeepSeekLLM(cfg)
