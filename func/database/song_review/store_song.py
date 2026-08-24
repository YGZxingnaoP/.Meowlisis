# -*- coding: utf-8 -*-
# func/database/song_review/store_song.py
# 唱完后把歌曲搜索结果写入知识库（去重、文档转移、向量分析）
from threading import Thread

from func.log.default_log import DefaultLog


class MeowSongStore:
    """歌曲信息入库：触发完整入库流程"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def store(self, song_title):
        Thread(target=self._store_async, args=(song_title,), daemon=True).start()

    def _store_async(self, song_title):
        from func.meowsinger.config import MeowSingerConfig
        template = MeowSingerConfig().search_prompt
        if not template:
            return
        guide = template.replace("{song_title}", song_title)
        try:
            from func.database.search.search_core import CatLearnSearch
            CatLearnSearch().start_search(guide, "song_review", "record")
        except Exception:
            self.log.exception("[SongReview] 入库搜索异常")
