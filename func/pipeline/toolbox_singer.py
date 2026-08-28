# -*- coding: utf-8 -*-
# func/pipeline/toolbox_singer.py
from func.log.default_log import DefaultLog


class ToolboxSingerBridge:
    def __init__(self):
        # 弹幕 → meowsinger 桥接
        self.log = DefaultLog().getLogger()

    def send_to_singer(self, text, username="", source="danmaku"):
        # 命中点歌/翻唱或唱歌中返回 True，否则 False
        if not text or not text.strip():
            return False
        try:
            from func.meowsinger.meowsinger_core import MeowSingerCore
            return MeowSingerCore().receive(text.strip(), username, source)
        except Exception:
            self.log.exception("弹幕 → meowsinger 处理异常")
            return False
