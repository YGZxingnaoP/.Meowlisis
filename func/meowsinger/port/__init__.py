# -*- coding: utf-8 -*-
# func/meowsinger/port/__init__.py
# meowsinger 独立 LLM 端口工厂：按配置返回 DeepSeek 或 Qwen 客户端
from func.meowsinger.config import MeowSingerConfig


def get_singer_llm():
    cfg = MeowSingerConfig()
    if cfg.llm_type == "gemini":
        from func.meowsinger.port.gemini import MeowSingerGeminiLLM
        return MeowSingerGeminiLLM(cfg)
    if cfg.llm_type == "aliyun":
        from func.meowsinger.port.aliyun import MeowSingerAliyunLLM
        return MeowSingerAliyunLLM(cfg)
    from func.meowsinger.port.deepseek import MeowSingerDeepSeekLLM
    return MeowSingerDeepSeekLLM(cfg)
