# -*- coding: utf-8 -*-
# func/database/song_review/review_core.py
# 唱歌感想协调器：接收唱歌信号，调度搜索摘要、入库、感想生成
# 感想在唱歌开始时就预生成，唱完直接播报；中途停止则直接舍弃
import os
import json
import time
import threading
from threading import Thread

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton

RESULT_PATH = os.path.join(".temp", "search_result.json")


@singleton
class MeowSongReview:
    """song_review 协调器（单例）：start_search / song_end / abandon

    - start_search：唱歌开始，触发搜索并后台预生成感想
    - song_end：唱完，播报已预生成的感想
    - abandon：中途停止，舍弃本次感想（不播报、不缓存）
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._cancelled = threading.Event()
        self._ready = threading.Event()
        self._feeling_text = ""
        self._feeling_segments = []

    def _reset(self):
        """每次唱歌开始前重置状态"""
        self._cancelled.clear()
        self._ready.clear()
        self._feeling_text = ""
        self._feeling_segments = []

    def start_search(self, song_title, mode="song"):
        """唱歌开始：触发歌曲搜索，并后台预生成感想"""
        self._reset()
        from func.database.song_review.get_song import MeowSongGetSong
        MeowSongGetSong().receive(song_title)
        Thread(target=self._prepare_feeling, args=(song_title, mode), daemon=True).start()

    def _prepare_feeling(self, song_title, mode):
        """后台预生成感想：等搜索结果 → 读歌词 → 构建引导词 → LLM 生成（不播报）"""
        try:
            search_result = self._wait_and_take_result()
            if self._cancelled.is_set():
                return

            try:
                from func.database.song_review.get_lyrics import MeowSongGetLyrics
                lrc = MeowSongGetLyrics().read(song_title, mode)
            except Exception:
                lrc = ""
            if self._cancelled.is_set():
                return

            try:
                from func.database.song_review.build_prompt_song import MeowSongBuildPrompt
                from func.pipeline.config_reader import ConfigReader
                sentiment = ConfigReader().get('meowsinger', {}).get('sentiment', {})
                word_count = int(sentiment.get('word_count', 300) or 300)
                guide = MeowSongBuildPrompt().build(song_title, mode, lrc, search_result, word_count)
            except Exception:
                self.log.exception("[SongReview] 构建引导词异常")
                return

            if not guide or self._cancelled.is_set():
                return

            from func.pipeline.database_llm import DatabaseLLMBridge
            cleaned_content, segments = DatabaseLLMBridge().generate(guide)
            if self._cancelled.is_set():
                return
            if segments:
                self._feeling_text = cleaned_content
                self._feeling_segments = segments
                self._ready.set()
        except Exception:
            self.log.exception("[SongReview] 感想预生成异常")

    def song_end(self, song_title, mode):
        Thread(target=self._song_end_async, args=(song_title, mode), daemon=True).start()

    def _song_end_async(self, song_title, mode):
        try:
            from func.database.song_review.store_song import MeowSongStore
            MeowSongStore().store(song_title)
        except Exception:
            self.log.exception("[SongReview] 入库触发异常")

        # 等预生成的感想（唱歌期间通常已生成好，这里只兜底等 LLM 尾巴）
        for _ in range(600):
            if self._cancelled.is_set():
                return
            if self._ready.is_set():
                break
            time.sleep(0.2)
        feeling_text = self._feeling_text
        feeling_segments = self._feeling_segments
        if self._cancelled.is_set() or not feeling_segments:
            return

        try:
            from func.pipeline.database_llm import DatabaseLLMBridge
            DatabaseLLMBridge().broadcast(feeling_text, feeling_segments)
        except Exception:
            self.log.exception("[SongReview] 感想播报异常")

    def abandon(self):
        """中途停止：舍弃本次感想（不播报、不缓存），并清搜索摘要"""
        self._cancelled.set()
        self._ready.clear()
        self._feeling_text = ""
        self._feeling_segments = []
        self._take_result()

    def _wait_and_take_result(self):
        for _ in range(300):
            if self._cancelled.is_set():
                return ""
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
