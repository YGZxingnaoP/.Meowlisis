# -*- coding: utf-8 -*-
# func/pipeline/tts_desktopet.py
# TTS 播放状态 → 桌宠嘴部/身体桥接

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class TtsDesktopetBridge:
    """TTS 播放器状态 → 桌宠表现桥接

    - 播放开始时启动嘴部开合与身体摆动；
    - 播放停止时停止并回正/闭合。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._playing = False

    def set_playing(self, playing: bool):
        """写入播放状态（True=开始说话，False=停止）"""
        playing = bool(playing)
        if playing == self._playing:
            return
        self._playing = playing
        try:
            if playing:
                from func.vts.desktopet.mouth_sync import DesktopetMouthSync
                from func.vts.desktopet.body_sway import DesktopetBodySway
                DesktopetMouthSync().start()
                DesktopetBodySway().start()
            else:
                from func.vts.desktopet.mouth_sync import DesktopetMouthSync
                from func.vts.desktopet.body_sway import DesktopetBodySway
                DesktopetMouthSync().stop()
                DesktopetBodySway().stop()
        except Exception:
            self.log.exception("TTS 播放状态 → 桌宠表现桥接异常")

    def is_playing(self) -> bool:
        """读取当前播放状态"""
        return self._playing
