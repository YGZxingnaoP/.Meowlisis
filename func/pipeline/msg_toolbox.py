# -*- coding: utf-8 -*-
# func/pipeline/msg_toolbox.py
# 统一输入 → Toolbox 桥接：把 msg / sensevoice 文本传递到 toolbox 做工具调用分析

from func.log.default_log import DefaultLog


class MsgToolboxBridge:
    """把 API / SenseVoice 输入的文本传递到 toolbox。

    - 仅负责把文本交给 TBoxCore.receive（→ analysis.decide 工具分析）；
    - 不负责 LLM 快速回复（快速回复由主 LLM 链路独立完成）；
    - 工具分析在独立线程执行，避免阻塞快速回复。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_toolbox(self, text: str, username: str = ""):
        """异步把文本送入 toolbox 工具分析链（analysis.decide）"""
        if not text or not text.strip():
            return
        from threading import Thread
        def _run():
            try:
                from func.toolbox.toolbox_core import TBoxCore
                TBoxCore().receive(text.strip(), username)
            except Exception:
                self.log.exception("msg → toolbox 工具分析异常")
        Thread(target=_run, daemon=True).start()
