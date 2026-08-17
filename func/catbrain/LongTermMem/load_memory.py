# -*- coding: utf-8 -*-
# func/catbrain/LongTermMem/load_memory.py
# 长期记忆加载：按配置天数读取最近 N 天聊天记录（仅源数据接口）

import os
import datetime

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig


class MeowLoadMemory:
    """长期记忆加载类：按回溯天数读取按日文件（当前仅提供源数据接口，不自动接入提示词）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.memory_dir = os.path.join("character", "memory")

    def load(self, days: int = None) -> str:
        """加载最近 N 天长期记忆并拼接为文本（天数从当天往前算，默认取配置）"""
        days = days if days is not None else self.config.memory_days
        texts = []
        today = datetime.date.today()
        for i in range(days):
            day = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            path = os.path.join(self.memory_dir, f"{day}.txt")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        texts.append(f.read())
                except Exception:
                    self.log.exception(f"读取长期记忆失败: {path}")
        return "\n".join(texts)
