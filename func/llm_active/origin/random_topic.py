# -*- coding: utf-8 -*-
# func/llm_active/origin/random_topic.py
# 创造型主动回复：随机话题与随机标签

import random

from func.catbrain.AbstractMem.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.tag_store import MeowTagStore


class AutoRandomTopic:
    """随机话题与标签：话题字典与 catbrain 一致，标签从 tags.json 读取"""

    def __init__(self):
        self.summary_tool = MeowSummaryTool()
        self.tag_store = MeowTagStore()

    def pick(self):
        """随机返回 (topic, tag)"""
        topic = random.choice(self.summary_tool.TOPICS)
        tags = self.tag_store.load()
        tag = random.choice(tags) if tags else ""
        return topic, tag
