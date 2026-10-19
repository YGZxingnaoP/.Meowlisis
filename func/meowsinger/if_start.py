# -*- coding: utf-8 -*-
# func/meowsinger/if_start.py
# 判断模块是否启动：前缀触发 / 关键词意图 / 空闲学歌指令，并统一提取歌名
from func.log.default_log import DefaultLog
from func.meowsinger.config import MeowSingerConfig
from func.tools.singleton_mode import singleton


@singleton
class MeowIfStart:
    """启动判断：返回 (mode, title, original) 或 (None, "", text)"""

    MODE_SONG = "song"
    MODE_COVER = "cover"
    MODE_LEARN = "learn"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowSingerConfig()
        self.learn_uids = self._load_learn_uids()

    def _load_learn_uids(self):
        """学歌授权用户：只认 meowid（六位编号 / temp-编号）。

        身份标准与 func/pipeline/id_signup.py 一致：meowid 是唯一身份键，昵称、QQ 号都不是。
        非 meowid 的配置项一律判非法并忽略，不做任何昵称/QQ 号回退解析。
        """
        from func.pipeline.id_signup import IdSignupBridge
        ident = IdSignupBridge()
        uids = set()
        for item in self.config.learn_users:
            if ident.is_internal_uid(item):
                uids.add(item)
            else:
                self.log.error(
                    f"[学歌] 学歌授权用户必须是 meowid（六位编号 / temp-编号），"
                    f"禁止填昵称或 QQ 号：{item!r} 已忽略")
        return uids

    def decide(self, text, username=""):
        """判断消息是否命中点歌/翻唱/学歌，返回 (mode, title, artist, original_text)"""
        if not text or not text.strip():
            return None, "", "", text or ""
        text = text.strip()

        # 学歌指令：仅空闲学习模式启用，指定用户精确全等匹配
        if self.config.learn_mode == "idle" and self._match_learn(text, username):
            return self.MODE_LEARN, "", "", text

        # 点歌前缀触发（大小写敏感，必须在最前）
        if self.config.song_enabled and self.config.song_trigger_mode in ("both", "prefix"):
            for prefix in self.config.song_prefix:
                if text.startswith(prefix):
                    original = text[len(prefix):].strip()
                    title, artist = self._extract_title(original)
                    return self.MODE_SONG, title or "", artist, original

        # 翻唱前缀触发
        if self.config.cover_enabled and self.config.cover_trigger_mode in ("both", "prefix"):
            for prefix in self.config.cover_prefix:
                if text.startswith(prefix):
                    original = text[len(prefix):].strip()
                    title, artist = self._extract_title(original)
                    return self.MODE_COVER, title or "", artist, original

        # 点歌关键词意图
        if (self.config.song_enabled
                and self.config.song_trigger_mode in ("both", "intent")
                and self._hit(self.config.song_intent, text)):
            title, artist = self._extract_title(text)
            if title:
                return self.MODE_SONG, title, artist, text

        # 翻唱关键词意图
        if (self.config.cover_enabled
                and self.config.cover_trigger_mode in ("both", "intent")
                and self._hit(self.config.cover_intent, text)):
            title, artist = self._extract_title(text)
            if title:
                return self.MODE_COVER, title, artist, text

        return None, "", "", text

    def _match_learn(self, text, username):
        # 入参就是 meowid（见 func/pipeline/id_signup.py），只做 meowid 全等比对
        if str(username or "").strip() not in self.learn_uids:
            return False
        return text == self.config.learn_trigger.strip()

    def _extract_title(self, text):
        if not text or not text.strip():
            return None, ""
        from func.meowsinger.get_title.get_title import MeowGetTitle
        return MeowGetTitle().extract(text)

    @staticmethod
    def _hit(keywords, text):
        return any(kw and kw in text for kw in keywords)
