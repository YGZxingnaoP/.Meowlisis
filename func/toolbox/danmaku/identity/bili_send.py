import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class TBDanmakuIdentitySend:
    def __init__(self):
        self.log = DefaultLog().getLogger()

    def _setting(self, key, default):
        """取绑定指令相关的弹幕发送设置"""
        try:
            from func.pipeline.config_reader import ConfigReader
            cfg = ConfigReader().get("identity", {}) or {}
            value = cfg.get(key)
            return default if value in (None, "") else value
        except Exception:
            return default

    def split(self, text):
        """按单条弹幕长度上限切分长回复"""
        try:
            limit = max(6, int(self._setting("danmaku_max_len", 20)))
        except Exception:
            limit = 20
        chunks = []
        for raw in str(text or "").split("\n"):
            line = raw.strip()
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            if line:
                chunks.append(line)
        return chunks

    def send(self, text):
        """把回复当纯文字弹幕发出去，不朗读也不进大模型"""
        chunks = self.split(text)
        if not chunks:
            return False
        try:
            interval = max(0.0, float(self._setting("danmaku_interval", 1.2)))
        except Exception:
            interval = 1.2
        ok = False
        try:
            from func.toolbox.danmaku.web.web_client import TBDanmakuWeb
            web = TBDanmakuWeb()
            for index, chunk in enumerate(chunks):
                if index:
                    time.sleep(interval)
                ok = bool(web.send_danmaku_sync(chunk)) or ok
        except Exception:
            self.log.exception("[Identity] 弹幕回复发送异常")
            return False
        if not ok:
            self.log.warning("[Identity] 弹幕回复发送失败：检查是否启用弹幕模块、是否配好 bili_jct 登录态")
        return ok
