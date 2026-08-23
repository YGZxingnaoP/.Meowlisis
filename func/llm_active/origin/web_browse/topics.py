# -*- coding: utf-8 -*-
# func/llm_active/origin/web_browse/topics.py
# 主题/话题相关工具：话题枚举复用 catbrain 摘要话题，主题枚举来自配置

from typing import List

from func.llm_active.origin.web_browse.config import AutoWebBrowseConfig


def get_summary_topics() -> List[str]:
    """话题枚举：复用 catbrain 摘要话题（与随机话题一致）"""
    try:
        from func.catbrain.AbstractMem.summary_tool import MeowSummaryTool
        return list(MeowSummaryTool.TOPICS)
    except Exception:
        return ["日常", "爱好", "哲思", "闲聊", "情感"]


def get_tags_pool() -> List[str]:
    """已有 tags：从 character/abstract_memory/tags/tags.json 读取"""
    try:
        from func.catbrain.AbstractMem.tag_store import MeowTagStore
        return list(MeowTagStore().load())
    except Exception:
        return []


def get_allow_topics() -> List[str]:
    """允许主题（采集过滤用），来自配置"""
    return list(AutoWebBrowseConfig().allow_topics)
