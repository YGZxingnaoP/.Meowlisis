# -*- coding: utf-8 -*-
# func/pipeline/get_subtitle.py
# 统一字幕桥：接收 TTS 播放字幕与歌词字幕，推送到浏览器字幕服务
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class GetSubtitleBridge:
    """字幕统一输出桥（单例）。

    - send_tts：推送 TTS 完整回复字幕（同文本去重，避免分段重复推送）；
    - send_lyric：推送歌词字幕（不去重，保证副歌重复句正常刷新）；
    - clear：清空字幕，回到待机两行。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._server = None
        self._last_tts = None

    def _ensure_server(self):
        if self._server is None:
            from func.subtitle.subtitle_server import get_subtitle_server
            self._server = get_subtitle_server()
        return self._server

    def send_tts(self, text):
        """推送 TTS 完整回复字幕（同文本去重）"""
        if not text:
            return
        if text == self._last_tts:
            return
        self._last_tts = text
        self._send(text)

    def send_lyric(self, text):
        """推送歌词字幕（不去重）"""
        if not text:
            return
        self._send(text)

    def clear(self):
        """清空字幕，回到待机状态"""
        self._last_tts = None
        self._send("__CLEAR__")

    def _send(self, text):
        try:
            self._ensure_server().send_subtitle(text)
        except Exception as e:
            self.log.error(f"发送字幕失败: {e}")
