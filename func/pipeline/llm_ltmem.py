# -*- coding: utf-8 -*-
# func/pipeline/llm_ltmem.py
# LLM → 长期记忆/摘要记忆/用户记忆 传递桥接（统一格式整合与分发）

import datetime

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.catbrain.LongTermMem.save_memory import MeowSaveMemory
from func.catbrain.AbstractMem.record.get_memory import MeowGetMemory
from func.catbrain.UserMemory.update_userinfo import MeowUpdateUserInfo


@singleton
class MeowLLMLtMemBridge:

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.save_memory = MeowSaveMemory()
        self.get_memory = MeowGetMemory()
        self.user_updater = MeowUpdateUserInfo()
        self.last_uid = ""

    def record_user_message(self, uid: str, text: str):
        line = self._format_line(uid, text)
        self.last_uid = uid
        self._dispatch(line, uid, is_user=True)

    def record_user_profile(self, uid: str, text: str):
        if not uid:
            return
        line = self._format_line(uid, text)
        self.last_uid = uid
        self.user_updater.record(uid, line, is_user=True)

    def record_ltmem_only(self, uid: str, text: str):
        line = self._format_line(uid, text)
        self.save_memory.save_line(line)
        self.get_memory.cache_message(line)

    def record_image_message(self, text: str):
        line = self.save_memory.save_image_line(text)
        self.get_memory.cache_message(line)

    def record_ai_message(self, uid: str, ai_name: str, text: str):
        line = self._format_line(ai_name, text)
        self._dispatch(line, uid, is_user=False)

    def record_ai_profile(self, uid: str, ai_name: str, text: str):
        if not uid:
            return
        line = self._format_line(ai_name, text)
        self.last_uid = uid
        self.user_updater.record(uid, line, is_user=False)

    def _dispatch(self, line: str, uid: str, is_user: bool):
        self.save_memory.save_line(line)
        self.get_memory.cache_message(line)
        self.user_updater.record(uid, line, is_user)

    @staticmethod
    def _format_line(uid: str, text: str) -> str:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        name = str(uid or "unknown").replace("\r", " ").replace("\n", " ")
        content = str(text or "").replace("\r", " ").replace("\n", " ")
        return f"[{now}][{name}]: {content}"
