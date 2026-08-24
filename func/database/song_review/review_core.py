# -*- coding: utf-8 -*-
# func/database/song_review/review_core.py
# 唱歌感想协调器：接收唱歌信号，调度搜索摘要、入库、感想生成
import os
import json
import time
from threading import Thread

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

RESULT_PATH = os.path.join(".temp", "search_result.json")


@singleton
class MeowSongReview:
    """song_review 协调器（单例）：start_search / song_end / abandon"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def start_search(self, song_title):
        from func.database.song_review.get_song import MeowSongGetSong
        MeowSongGetSong().receive(song_title)

    def song_end(self, song_title, mode):
        Thread(target=self._song_end_async, args=(song_title, mode), daemon=True).start()

    def abandon(self):
        self._take_result()

    def _song_end_async(self, song_title, mode):
        try:
            from func.database.song_review.store_song import MeowSongStore
            MeowSongStore().store(song_title)
        except Exception:
            self.log.exception("[SongReview] 入库触发异常")

        search_result = self._wait_and_take_result()
        try:
            from func.database.song_review.get_lyrics import MeowSongGetLyrics
            lrc = MeowSongGetLyrics().read(song_title, mode)
        except Exception:
            lrc = ""

        try:
            from func.database.song_review.build_prompt_song import MeowSongBuildPrompt
            from func.pipeline.config_reader import ConfigReader
            sentiment = ConfigReader().get('meowsinger', {}).get('sentiment', {})
            word_count = int(sentiment.get('word_count', 300) or 300)
            guide = MeowSongBuildPrompt().build(song_title, mode, lrc, search_result, word_count)
        except Exception:
            self.log.exception("[SongReview] 构建引导词异常")
            return

        if not guide:
            return

        try:
            from func.pipeline.database_llm import DatabaseLLMBridge
            DatabaseLLMBridge().send_guide(guide)
        except Exception:
            self.log.exception("[SongReview] 感想合成异常")

    def _wait_and_take_result(self):
        for _ in range(300):
            result = self._take_result()
            if result:
                return result
            time.sleep(0.2)
        return ""

    def _take_result(self):
        try:
            if not os.path.exists(RESULT_PATH):
                return ""
            with open(RESULT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return ""
            items = data.pop("song_review", None)
            if items is not None:
                with open(RESULT_PATH, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            if not items:
                return ""
            lines = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                summary = str(it.get("summary", "") or "").strip()
                if summary:
                    lines.append(summary)
            return "；".join(lines)
        except Exception:
            return ""
