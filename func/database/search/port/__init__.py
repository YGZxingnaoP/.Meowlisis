# -*- coding: utf-8 -*-
# func/database/search/port：搜索模块独立 LLM 端口（与 llm 相同，独立 apikey）

from func.database.config import CatLearnConfig


def get_search_llm():
    """按配置返回搜索模块 LLM 客户端（DeepSeek / Aliyun）"""
    cfg = CatLearnConfig()
    if cfg.search_llm_type == "aliyun":
        from func.database.search.port.aliyun import CatLearnSearchAliyunLLM
        return CatLearnSearchAliyunLLM()
    from func.database.search.port.deepseek import CatLearnSearchDeepSeekLLM
    return CatLearnSearchDeepSeekLLM()
