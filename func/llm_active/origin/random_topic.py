# -*- coding: utf-8 -*-
# func/llm_active/origin/random_topic.py
# 创造型主动回复：随机话题与随机标签（统一随机池：话题 + 缓存视频）

import json
import random

from func.catbrain.AbstractMem.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.tag_store import MeowTagStore


class AutoRandomTopic:
    """随机话题/视频：话题字典与 catbrain 一致，视频来自 web_browse 缓存"""

    def __init__(self):
        self.summary_tool = MeowSummaryTool()
        self.tag_store = MeowTagStore()

    def pick(self):
        """从统一随机池抽取一项。

        返回 dict：
          - {"type": "topic", "topic": str, "tag": str}   → 走记忆
          - {"type": "video", "path": str, "data": dict}  → 走视频内容
        """
        topic = random.choice(self.summary_tool.TOPICS)
        tags = self.tag_store.load()
        tag = random.choice(tags) if tags else ""
        topic_item = {"type": "topic", "topic": topic, "tag": tag}

        pool = [topic_item]
        try:
            from func.llm_active.origin.web_browse.store import AutoBrowseStore
            for path in AutoBrowseStore().list_cache():
                data = self._load_json(path)
                if data:
                    pool.append({"type": "video", "path": path, "data": data})
        except Exception:
            pass

        return random.choice(pool) if pool else topic_item

    @staticmethod
    def _load_json(path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None
