# -*- coding: utf-8 -*-
# func/meowsinger/netease/get_song.py
# 点歌流程：下载歌曲 → 报歌名 → 播放 → 结束信号（字幕先保留方法）
import os
import time
from threading import Thread

from func.log.default_log import DefaultLog
from func.meowsinger.config import MeowSingerConfig
from func.meowsinger.netease.netease_music import MeowNeteaseMusic
from func.meowsinger.singerplayer import MeowSingerPlayer


class MeowNeteaseSong:
    """点歌模块：负责网易云搜歌下载与播放"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowSingerConfig()
        self.ncm = MeowNeteaseMusic()
        self.player = MeowSingerPlayer()

    def play(self, title, artist="", username=""):
        """点歌入口：异步执行下载与播放"""
        Thread(target=self._play_async, args=(title, artist, username), daemon=True).start()

    def _end_singing(self):
        # 失败路径兜底清除唱歌占用
        try:
            from func.pipeline.singing_state import SingingStateBridge
            SingingStateBridge().end_singing()
        except Exception:
            pass

    def _play_async(self, title, artist, username):
        if not title or not title.strip():
            self._reply_no_title(username)
            self._end_singing()
            return
        title = title.strip()

        info = self.ncm.search_and_download(title, artist)
        if not info:
            self._reply_fail(title, username)
            self._end_singing()
            return
        mp3_path = self.ncm.save_song(info.get("songname", title), info)

        self._announce(info.get("songname", title))
        self._wait_tts_idle()

        from func.pipeline.singing_state import SingingStateBridge
        SingingStateBridge().start_singing("song", info.get("songname", title))
        self._send_start_signal(info.get("songname", title))

        from func.meowsinger.subtitle.lyric_syncer import MeowLyricSyncer
        syncer = MeowLyricSyncer()
        lrc_path = os.path.splitext(mp3_path)[0] + ".lrc"
        syncer.start(MeowLyricSyncer.parse_lrc_file(lrc_path))

        finished = self.player.play_file(mp3_path)

        syncer.stop()
        SingingStateBridge().end_singing()
        self._subtitle_done()
        if finished:
            self._send_end_signal(info.get("songname", title))
        self.log.info(f"[点歌] 播放结束: {title} finished={finished}")

    def _announce(self, songname):
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().send_stream(f"接下来播放《{songname}》", source="meowsinger")
        except Exception:
            self.log.exception("[点歌] 报歌名异常")

    def _wait_tts_idle(self):
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            bridge = ToolboxTtsBridge()
            for _ in range(200):
                if not bridge.is_busy():
                    return
                time.sleep(0.1)
            self.log.warning("[点歌] 等待 TTS 空闲超时，继续播放")
        except Exception:
            pass

    def _send_start_signal(self, title):
        try:
            from func.pipeline.singer_database import SingerDatabaseBridge
            SingerDatabaseBridge().start_search(title, "song")
        except Exception:
            self.log.exception("[点歌] 开始信号异常")

    def _send_end_signal(self, title):
        try:
            from func.pipeline.singer_database import SingerDatabaseBridge
            SingerDatabaseBridge().song_end(title, "song")
        except Exception:
            self.log.exception("[点歌] 结束信号异常")

    def _subtitle_done(self):
        pass

    def _reply_no_title(self, username):
        try:
            from func.pipeline.singer_llm import SingerLLMBridge
            SingerLLMBridge().send_reply("没有相关的歌名", username)
        except Exception:
            self.log.exception("[点歌] 回复无歌名异常")

    def _reply_fail(self, title, username):
        try:
            from func.pipeline.singer_llm import SingerLLMBridge
            SingerLLMBridge().send_reply(f"没有找到歌曲《{title}》", username)
        except Exception:
            self.log.exception("[点歌] 回复失败异常")
