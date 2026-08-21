# -*- coding: utf-8 -*-
# func/pipeline/msg_database.py
# 消息 → database 桥接：把 msg/sensevoice/qq 文本传递到 database_core 做关键词匹配

from func.log.default_log import DefaultLog


class MsgDatabaseBridge:
    """把 API / SenseVoice / QQ 输入文本传递到 database_core。

    - 仅负责把文本交给 CatLearnCore.on_message（关键词匹配 + 记录）；
    - 不负责 LLM 回复；
    - 在独立线程执行，避免阻塞快速回复。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_database(self, text: str, username: str = ""):
        """异步把文本送入 database_core 关键词匹配链"""
        if not text or not text.strip():
            return
        from threading import Thread

        def _run():
            try:
                from func.database.database_core import CatLearnCore
                CatLearnCore().on_message(text.strip(), username)
            except Exception:
                self.log.exception("msg → database 处理异常")

        Thread(target=_run, daemon=True).start()
