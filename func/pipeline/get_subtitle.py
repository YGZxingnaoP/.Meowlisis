# -*- coding: utf-8 -*-
# func/pipeline/get_subtitle.py
# 统一字幕桥：接收 TTS 播放字幕/ASR 识别字幕/歌词字幕，推送到浏览器字幕服务
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class GetSubtitleBridge:
    """字幕统一输出桥（单例）。

    - send_tts：推送 TTS 完整回复字幕（AI 说话内容，标签显示 AI 角色名）；
    - send_asr：推送 ASR 语音识别字幕（用户说话内容，标签显示说话用户名）；
    - send_lyric：推送歌词字幕（不去重，保证副歌重复句正常刷新）；
    - clear：清空字幕，回到待机两行。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._server = None
        self._last_tts = None
        self._last_asr = None
        self._ai_name_cache = None

    def _ensure_server(self):
        if self._server is None:
            from func.subtitle.subtitle_server import get_subtitle_server
            self._server = get_subtitle_server()
        return self._server

    def _ai_name(self):
        """AI 角色名称（AppConfig.ai_name），作为 tts 字幕标签"""
        if self._ai_name_cache is None:
            try:
                from func.config.app_config import AppConfig
                self._ai_name_cache = getattr(AppConfig(), "ai_name", "") or 'AI'
            except Exception:
                self._ai_name_cache = 'AI'
        return self._ai_name_cache

    def send_tts(self, text):
        """推送 TTS 完整回复字幕（同文本去重）"""
        if not text:
            return
        if text == self._last_tts:
            return
        self._last_tts = text
        self._send(text, role='tts', name=self._ai_name())

    def send_asr(self, text, username=None):
        """推送 ASR 语音识别字幕（用户说话内容，同文本去重；username 作为标签）"""
        if not text:
            return
        if text == self._last_asr:
            return
        self._last_asr = text
        self._send(text, role='asr', name=username or '说话人')

    def send_lyric(self, text):
        """推送歌词字幕（不去重）"""
        if not text:
            return
        self._send(text, role='lyric', name=self._ai_name())

    def clear(self):
        """清空字幕，回到待机状态"""
        self._last_tts = None
        self._last_asr = None
        self._send("", role='clear')

    def _send(self, text, role='tts', name=None):
        try:
            self._ensure_server().send_subtitle(text, role=role, name=name)
        except Exception as e:
            self.log.error(f"发送字幕失败: {e}")
