# -*- coding: utf-8 -*-
# func/pipeline/msg_singer.py
# msg / sensevoice / 弹幕 → meowsinger 桥接：命中点歌翻唱或唱歌中则拦截
from func.log.default_log import DefaultLog


class MsgSingerBridge:
    """把 API / SenseVoice / 弹幕文本传递到 meowsinger。

    - 命中点歌/翻唱触发词：走 meowsinger 流程并返回 True（上层跳过主 LLM 回复）；
    - 正在唱歌：消息进汇总池并返回 True（唱歌结束后统一回复）；
    - 未命中：返回 False（上层继续原链路）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_singer(self, text, username="", source="msg"):
        if not text or not text.strip():
            return False
        try:
            from func.meowsinger.meowsinger_core import MeowSingerCore
            return MeowSingerCore().receive(text.strip(), username, source)
        except Exception:
            self.log.exception("msg → meowsinger 处理异常")
            return False

    def trigger_summary(self):
        """触发唱歌汇总回复（感想播报后统一回复唱歌期间的汇总消息）"""
        try:
            from func.meowsinger.meowsinger_core import MeowSingerCore
            MeowSingerCore().process_sing_summary()
        except Exception:
            self.log.exception("trigger_summary 触发异常")
