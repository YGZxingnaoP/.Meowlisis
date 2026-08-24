# -*- coding: utf-8 -*-
# func/meowsinger/stop.py
# 停止检测：关键词命中则掐断播放并通知 database 放弃感想
from func.log.default_log import DefaultLog
from func.meowsinger.config import MeowSingerConfig
from func.tools.singleton_mode import singleton


@singleton
class MeowStop:
    """停止播放检测与执行（关键词可被子串包含）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowSingerConfig()

    def is_stop(self, text):
        """判断文本是否命中停止触发词"""
        if not text:
            return False
        return any(kw and kw in text for kw in self.config.stop_keywords)

    def trigger_stop(self):
        """执行停止：停止播放、清空汇总池、结束唱歌状态并通知 database 放弃感想"""
        try:
            from func.meowsinger.singerplayer import MeowSingerPlayer
            MeowSingerPlayer().stop()
            from func.meowsinger.state import MeowSingerState
            MeowSingerState().take_pending_messages()
            from func.pipeline.singing_state import SingingStateBridge
            SingingStateBridge().end_singing()
            from func.pipeline.singer_database import SingerDatabaseBridge
            SingerDatabaseBridge().abandon()
            self.log.info("[MeowStop] 唱歌已掐断，放弃感想合成")
        except Exception:
            self.log.exception("[MeowStop] 停止执行异常")
