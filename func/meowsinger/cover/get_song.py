# -*- coding: utf-8 -*-
# func/meowsinger/cover/get_song.py
# 翻唱流程：判断是否学过 → 播放或学习 → 空闲学歌任务串行执行
import os
import time
from threading import Thread

from func.log.default_log import DefaultLog
from func.meowsinger.config import MeowSingerConfig
from func.meowsinger.state import MeowSingerState
from func.meowsinger.cover.cover_core import MeowCoverCore
from func.meowsinger.singerplayer import MeowSingerPlayer


class MeowCoverSong:
    """翻唱模块：负责翻唱播放与学歌任务调度"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowSingerConfig()
        self.state = MeowSingerState()
        self.core = MeowCoverCore()
        self.player = MeowSingerPlayer()

    def cover(self, title, username):
        """翻唱入口：异步执行判断与播放/学习"""
        Thread(target=self._cover_async, args=(title, username), daemon=True).start()

    def _cover_async(self, title, username):
        if not title or not title.strip():
            self._reply_no_title(username)
            return
        title = title.strip()

        if self.core.has_learned(title):
            self._play_learned(title)
            return

        # 未学过：确保 raw_list 有原曲
        mp3_path = self.core.raw_mp3_path(title)
        if not os.path.exists(mp3_path):
            mp3_path, title = self._download_raw(title)
        if not mp3_path or not os.path.exists(mp3_path):
            self._reply_fail(title, username)
            return

        if self.config.learn_mode == "immediate":
            self.state.set_learning(True)
            success = self.core.learn_song(title, mp3_path)
            self.state.set_learning(False)
            if success:
                self._play_learned(title)
            else:
                self._reply_learn_fail(title, username)
        else:
            self.state.add_rvc_task({"title": title, "mp3_path": mp3_path})
            self._reply_need_learn(title, username)

    def start_learn(self, username):
        """学歌指令触发：依次串行执行 rvc 队列，不中断"""
        Thread(target=self._learn_queue, args=(username,), daemon=True).start()

    def _learn_queue(self, username):
        self.state.set_learning(True)
        try:
            while self.state.has_rvc_task():
                task = self.state.pop_rvc_task()
                title = task.get("title", "")
                mp3_path = task.get("mp3_path", "")
                self.log.info(f"[学歌] 开始学习: {title}")
                success = self.core.learn_song(title, mp3_path)
                self._notify_learn_done(title, success, username)
                time.sleep(0.5)
        finally:
            self.state.set_learning(False)

    def _play_learned(self, title):
        folder = os.path.join("character", "songs", "meow_list", self._safe_name(title))
        vocal = os.path.join(folder, f"{self._safe_name(title)}_vocal.wav")
        accomp = os.path.join(folder, f"{self._safe_name(title)}_accomp.wav")
        harmony = os.path.join(folder, f"{self._safe_name(title)}_harmony.wav")
        self._interrupt_tts()
        self._announce(title)
        self._wait_tts_idle()

        mixed = self.core.mix_tracks(vocal, accomp, harmony)
        if mixed is None:
            self.log.error(f"[翻唱] 混音失败: {title}")
            return
        audio, sr = mixed

        from func.pipeline.singing_state import SingingStateBridge
        SingingStateBridge().start_singing("cover", title)
        self._send_start_signal(title)

        from func.meowsinger.subtitle.lyric_syncer import MeowLyricSyncer
        syncer = MeowLyricSyncer()
        lrc_path = os.path.join(folder, f"{self._safe_name(title)}.lrc")
        syncer.start(MeowLyricSyncer.parse_lrc_file(lrc_path))

        finished = self.player.play_audio(audio, sr)

        syncer.stop()
        SingingStateBridge().end_singing()
        if finished:
            self._send_end_signal(title)
        self.log.info(f"[翻唱] 播放结束: {title} finished={finished}")

    def _download_raw(self, title):
        """下载原曲，返回 (mp3路径, 实际歌名)"""
        try:
            from func.meowsinger.netease.netease_music import MeowNeteaseMusic
            ncm = MeowNeteaseMusic()
            info = ncm.search_and_download(title)
            if not info:
                return "", title
            songname = info.get("songname", title)
            mp3 = ncm.save_song(songname, info)
            return mp3, songname
        except Exception:
            self.log.exception("[翻唱] 下载原曲异常")
            return "", title

    def _interrupt_tts(self):
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().interrupt()
        except Exception:
            self.log.exception("[翻唱] 打断 TTS 异常")

    def _announce(self, title):
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            ToolboxTtsBridge().send_stream(f"接下来翻唱《{title}》", source="meowsinger")
        except Exception:
            self.log.exception("[翻唱] 报歌名异常")

    def _wait_tts_idle(self):
        try:
            from func.pipeline.toolbox_tts import ToolboxTtsBridge
            bridge = ToolboxTtsBridge()
            for _ in range(200):
                if not bridge.is_busy():
                    return
                time.sleep(0.1)
            self.log.warning("[翻唱] 等待 TTS 空闲超时，继续播放")
        except Exception:
            pass

    def _send_start_signal(self, title):
        try:
            from func.pipeline.singer_database import SingerDatabaseBridge
            SingerDatabaseBridge().start_search(title, "cover")
        except Exception:
            self.log.exception("[翻唱] 开始信号异常")

    def _send_end_signal(self, title):
        try:
            from func.pipeline.singer_database import SingerDatabaseBridge
            SingerDatabaseBridge().song_end(title, "cover")
        except Exception:
            self.log.exception("[翻唱] 结束信号异常")

    def _notify_learn_done(self, title, success, username):
        try:
            from func.pipeline.singer_llm import SingerLLMBridge
            if success:
                SingerLLMBridge().send_reply(f"已经学会《{title}》啦", username)
            else:
                SingerLLMBridge().send_reply(f"学习《{title}》失败了", username)
        except Exception:
            self.log.exception("[翻唱] 学习结果通知异常")

    def _reply_no_title(self, username):
        try:
            from func.pipeline.singer_llm import SingerLLMBridge
            SingerLLMBridge().send_reply("没有相关的歌名", username)
        except Exception:
            self.log.exception("[翻唱] 回复无歌名异常")

    def _reply_fail(self, title, username):
        try:
            from func.pipeline.singer_llm import SingerLLMBridge
            SingerLLMBridge().send_reply(f"没有找到歌曲《{title}》", username)
        except Exception:
            self.log.exception("[翻唱] 回复失败异常")

    def _reply_need_learn(self, title, username):
        try:
            from func.pipeline.singer_llm import SingerLLMBridge
            SingerLLMBridge().send_reply(f"《{title}》还没有学过，下次再唱给你听", username)
        except Exception:
            self.log.exception("[翻唱] 回复需学习异常")

    def _reply_learn_fail(self, title, username):
        try:
            from func.pipeline.singer_llm import SingerLLMBridge
            SingerLLMBridge().send_reply(f"《{title}》学习失败了", username)
        except Exception:
            self.log.exception("[翻唱] 回复学习失败异常")

    @staticmethod
    def _safe_name(name):
        import re
        return re.sub(r'[\\/:*?"<>|]', "_", str(name or "")).strip() or "未命名"
