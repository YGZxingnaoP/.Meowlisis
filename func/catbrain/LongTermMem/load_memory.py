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

    def load_recent(self, username: str, lines: int = None) -> list:
        """读取最近三天中包含指定用户的原始记录（按时间顺序，最多 lines 条）"""
        lines = lines if lines is not None else self.config.memory_inject_recent_lines
        if not username or int(lines or 0) <= 0:
            return []
        tag = f"[{username}]"
        collected = []
        today = datetime.date.today()
        for offset in (2, 1, 0):
            day = (today - datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
            path = os.path.join(self.memory_dir, f"{day}.txt")
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        if tag in line:
                            collected.append(line.rstrip("\n"))
            except Exception:
                self.log.exception(f"读取长期记忆失败: {path}")
            if len(collected) >= lines:
                break
        return collected[-lines:]

    def build(self, username: str = "") -> str:
        """构建当前用户最近原文提示词块（开关关闭或无内容时返回空串）"""
        if not self.config.memory_inject_recent:
            return ""
        rows = self.load_recent(username)
        if not rows:
            return ""
        return "# 最近的原始对话记录\n" + "\n".join(rows)
