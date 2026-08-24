# -*- coding: utf-8 -*-
# func/database/song_review/get_song.py
# 从 singer_database 收到歌名，触发歌曲搜索
from func.log.default_log import DefaultLog


class MeowSongGetSong:
    """歌名接收入口：收到歌名后触发搜索与摘要"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def receive(self, song_title):
        if not song_title or not song_title.strip():
            return
        try:
            from func.database.song_review.search_song import MeowSongSearch
            MeowSongSearch().search(song_title.strip())
        except Exception:
            self.log.exception("[SongReview] 触发搜索异常")
