# -*- coding: utf-8 -*-
# func/pipeline/llm_ltmem.py
# LLM → 长期记忆/摘要记忆/用户记忆 传递桥接（统一格式整合与分发）

import datetime

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.catbrain.LongTermMem.save_memory import MeowSaveMemory
from func.catbrain.AbstractMem.get_memory import MeowGetMemory
from func.catbrain.UserMemory.update_userinfo import MeowUpdateUserInfo


@singleton
class MeowLLMLtMemBridge:
    """LLM 长期记忆桥接：格式化消息并分发到存储、摘要缓存与用户记忆"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.save_memory = MeowSaveMemory()
        self.get_memory = MeowGetMemory()
        self.user_updater = MeowUpdateUserInfo()
        # 当前用户（最近一次发送消息的用户，供 load_usrmem 等模块获取）
        self.last_username = ""

    def record_user_message(self, username: str, text: str):
        """记录用户消息：写入长期记忆、混杂摘要缓存、用户记忆计数，并更新当前用户"""
        line = self._format_line(username, text)
        self.last_username = username
        self._dispatch(line, username, is_user=True)

    def record_ai_message(self, username: str, ai_name: str, text: str):
        """记录 AI 回复：以 AI 名字写入长期记忆，同步缓存供摘要与用户记忆上下文"""
        line = self._format_line(ai_name, text)
        self._dispatch(line, username, is_user=False)

    def _dispatch(self, line: str, username: str, is_user: bool):
        """分发一条记录到长期记忆存储、摘要缓存与用户记忆"""
        self.save_memory.save_line(line)
        self.get_memory.cache_message(line)
        self.user_updater.record(username, line, is_user)

    @staticmethod
    def _format_line(username: str, text: str) -> str:
        """格式化为 [时间][用户名]: 内容（去除换行保证单行存储）"""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        name = str(username or "用户").replace("\r", " ").replace("\n", " ")
        content = str(text or "").replace("\r", " ").replace("\n", " ")
        return f"[{now}][{name}]: {content}"
