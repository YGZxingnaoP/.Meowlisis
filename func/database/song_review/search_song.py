# -*- coding: utf-8 -*-
# func/database/song_review/search_song.py
# 收到歌名后走关键词触发的搜索，生成摘要存 .temp/search_result
from threading import Thread

from func.log.default_log import DefaultLog


class MeowSongSearch:
    """歌曲搜索摘要：moegirl/baidu 搜索并生成 llm 摘要"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def search(self, song_title):
        Thread(target=self._search_async, args=(song_title,), daemon=True).start()

    def _search_async(self, song_title):
        from func.meowsinger.config import MeowSingerConfig
        template = MeowSingerConfig().search_prompt
        if not template:
            return
        guide = template.replace("{song_title}", song_title)
        try:
            from func.database.search.search_core import CatLearnSearch
            CatLearnSearch().start_search(guide, "song_review", "keyword")
        except Exception:
            self.log.exception("[SongReview] 关键词搜索摘要异常")
