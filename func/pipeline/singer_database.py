# -*- coding: utf-8 -*-
# func/pipeline/singer_database.py
# meowsinger → database song_review 桥接：搜索任务、唱歌结束、放弃感想
from func.log.default_log import DefaultLog


class SingerDatabaseBridge:
    """把 meowsinger 的唱歌信号传递给 database/song_review。

    - start_search：唱歌开始时触发歌曲搜索（生成摘要）；
    - song_end：完整唱完后触发入库与感想生成；
    - abandon：提前掐断时放弃感想合成并清除搜索摘要。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def start_search(self, song_title, mode="song"):
        if not song_title:
            return
        try:
            from func.database.song_review.review_core import MeowSongReview
            MeowSongReview().start_search(song_title, mode)
        except Exception:
            self.log.exception("singer → database 搜索触发异常")

    def song_end(self, song_title, mode):
        if not song_title:
            return
        try:
            from func.database.song_review.review_core import MeowSongReview
            MeowSongReview().song_end(song_title, mode)
        except Exception:
            self.log.exception("singer → database 结束信号异常")

    def abandon(self):
        try:
            from func.database.song_review.review_core import MeowSongReview
            MeowSongReview().abandon()
        except Exception:
            self.log.exception("singer → database 放弃信号异常")
