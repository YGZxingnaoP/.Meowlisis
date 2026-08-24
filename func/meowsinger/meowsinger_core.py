# -*- coding: utf-8 -*-
# func/meowsinger/meowsinger_core.py
# meowsinger 核心：接收消息、判断点歌/翻唱/学歌/停止、唱歌中拦截汇总
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.meowsinger.config import MeowSingerConfig
from func.meowsinger.state import MeowSingerState
from func.meowsinger.if_start import MeowIfStart
from func.meowsinger.stop import MeowStop


@singleton
class MeowSingerCore:
    """meowsinger 核心调度：命中点歌/翻唱/学歌走对应流程，唱歌中拦截汇总"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowSingerConfig()
        self.state = MeowSingerState()
        self.if_start = MeowIfStart()
        self.stop = MeowStop()

    def receive(self, text, username="", source="msg"):
        """接收一条消息，返回 True 表示已拦截（命中或唱歌中），False 放行"""
        if not self.config.enabled:
            return False
        if not text or not text.strip():
            return False
        text = text.strip()
        username = username or "主人"

        # 唱歌中：停止词则掐断，否则进汇总池并拦截
        if self.state.is_singing():
            if self.stop.is_stop(text):
                self.stop.trigger_stop()
            else:
                self.state.add_pending_message(username, text, source)
            return True

        # 启动判断
        mode, title, original = self.if_start.decide(text, username)

        # 空闲学歌指令
        if mode == MeowIfStart.MODE_LEARN:
            self._record_user(username, original)
            self._start_learn(username)
            return True

        # 点歌
        if mode == MeowIfStart.MODE_SONG:
            self._record_user(username, original)
            self._dispatch_song(title, username)
            return True

        # 翻唱
        if mode == MeowIfStart.MODE_COVER:
            self._record_user(username, original)
            self._dispatch_cover(title, username)
            return True

        return False

    def _dispatch_song(self, title, username):
        try:
            from func.meowsinger.netease.get_song import MeowNeteaseSong
            MeowNeteaseSong().play(title, username)
        except Exception:
            self.log.exception("[MeowSinger] 点歌流程异常")

    def _dispatch_cover(self, title, username):
        try:
            from func.meowsinger.cover.get_song import MeowCoverSong
            MeowCoverSong().cover(title, username)
        except Exception:
            self.log.exception("[MeowSinger] 翻唱流程异常")

    def _start_learn(self, username):
        try:
            from func.meowsinger.cover.get_song import MeowCoverSong
            MeowCoverSong().start_learn(username)
        except Exception:
            self.log.exception("[MeowSinger] 学歌触发异常")

    def process_sing_summary(self):
        """唱歌结束后统一回复唱歌期间汇总的消息"""
        from threading import Thread
        Thread(target=self._summary_async, daemon=True).start()

    def _summary_async(self):
        messages = self.state.take_pending_messages()
        if not messages:
            return
        lines = "\n".join(f"{m.get('username', '观众')}说：{m.get('text', '')}" for m in messages)
        try:
            from func.pipeline.singer_llm import SingerLLMBridge
            SingerLLMBridge().send_summary(lines)
        except Exception:
            self.log.exception("[MeowSinger] 唱歌汇总回复异常")

    @staticmethod
    def _record_user(username, text):
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save({"role": "user", "content": text, "type": "llm_fast_response"},
                               40, trim_mode="rounds")
        except Exception:
            pass
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            MeowLLMLtMemBridge().record_user_message(username, text)
        except Exception:
            pass
