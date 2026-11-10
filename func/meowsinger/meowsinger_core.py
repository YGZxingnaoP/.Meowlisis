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

    def receive(self, text, meowid="", source="msg"):
        """接收一条消息，返回 True 表示已拦截（命中或唱歌中），False 放行"""
        if not self.config.enabled:
            return False
        if not text or not text.strip():
            return False
        text = text.strip()
        # 身份标准：只接受内部编号，缺身份直接放行（禁止用「主人」等默认身份兜底）
        meowid = str(meowid or "").strip()
        if not meowid:
            self.log.error("[meowsinger] 缺少身份编号，不接管本条")
            return False
        try:
            from func.pipeline.id_signup import IdSignupBridge
            if not IdSignupBridge.is_internal_uid(meowid):
                self.log.error(f"[meowsinger] 非标准 meowid，不接管：{meowid!r}")
                return False
        except Exception:
            self.log.exception("[meowsinger] meowid 校验异常")

        # 唱歌中：停止词则掐断，否则进汇总池并拦截
        if self.state.is_singing():
            if self.stop.is_stop(text):
                self.stop.trigger_stop()
            else:
                self.state.add_pending_message(meowid, text, source)
            return True

        # 静默中：不触发新点歌/翻唱/学歌（正在唱歌的停止词不受影响）
        try:
            from func.pipeline.silence_state import SilenceState
            if SilenceState().muted:
                return False
        except Exception:
            pass

        # 启动判断
        mode, title, artist, original = self.if_start.decide(text, meowid)

        # 空闲学歌指令
        if mode == MeowIfStart.MODE_LEARN:
            self._record_user(meowid, original)
            self._start_learn(meowid)
            return True

        # 点歌
        if mode == MeowIfStart.MODE_SONG:
            self._record_user(meowid, original)
            self._mark_singing("song", title or "")
            self._dispatch_song(title, artist, meowid)
            return True

        # 翻唱
        if mode == MeowIfStart.MODE_COVER:
            self._record_user(meowid, original)
            self._mark_singing("cover", title or "")
            self._dispatch_cover(title, artist, meowid)
            return True

        return False

    def _mark_singing(self, mode, title):
        # 命中点歌/翻唱即标记占用，避免下载/报歌名窗口内二次触发
        try:
            from func.pipeline.singing_state import SingingStateBridge
            SingingStateBridge().start_singing(mode, title or "")
        except Exception:
            self.log.exception("[MeowSinger] 标记唱歌占用异常")

    def _dispatch_song(self, title, artist, meowid):
        try:
            from func.meowsinger.netease.get_song import MeowNeteaseSong
            MeowNeteaseSong().play(title, artist, meowid)
        except Exception:
            self.log.exception("[MeowSinger] 点歌流程异常")

    def _dispatch_cover(self, title, artist, meowid):
        try:
            from func.meowsinger.cover.get_song import MeowCoverSong
            MeowCoverSong().cover(title, artist, meowid)
        except Exception:
            self.log.exception("[MeowSinger] 翻唱流程异常")

    def _start_learn(self, meowid):
        try:
            from func.meowsinger.cover.get_song import MeowCoverSong
            MeowCoverSong().start_learn(meowid)
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
        lines = "\n".join(f"{m.get('meowid', '观众')}说：{m.get('text', '')}" for m in messages)
        uid = next((str(m.get("meowid") or "").strip() for m in messages
                    if str(m.get("meowid") or "").strip()), "")
        try:
            from func.pipeline.singer_llm import SingerLLMBridge
            SingerLLMBridge().send_summary(lines, uid=uid)
        except Exception:
            self.log.exception("[MeowSinger] 唱歌汇总回复异常")

    @staticmethod
    def _record_user(meowid, text):
        try:
            from func.pipeline.short_memory import ShortMemory
            ShortMemory().save({"role": "user", "content": text, "type": "llm_fast_response"},
                               40, trim_mode="rounds")
        except Exception:
            pass
        try:
            from func.pipeline.llm_ltmem import MeowLLMLtMemBridge
            MeowLLMLtMemBridge().record_user_message(meowid, text)
        except Exception:
            pass
