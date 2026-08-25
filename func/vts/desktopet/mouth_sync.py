# -*- coding: utf-8 -*-
# func/vts/desktopet/mouth_sync.py
# 桌宠嘴部同步控制器：仅由 TTS 播放器状态驱动（播放时随机开合，停止时闭合）

import random
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.vts.desktopet.config import DesktopetConfig
from func.vts.desktopet.vts_init import DesktopetInit


@singleton
class DesktopetMouthSync:
    """嘴部同步：后台线程按周期发送随机开合值，停止时闭合"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = DesktopetConfig()
        self.desktopet = DesktopetInit()
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()

    def start(self):
        """开始嘴部开合（播放时调用）"""
        if not self.config.switch or not self.config.mouth_sync_enabled:
            return
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止嘴部开合并闭合（停止播放时调用）"""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        self.desktopet.send_parameter(self.config.mouth_sync_parameter, self.config.mouth_sync_close)

    def _loop(self):
        cfg = self.config
        while self._running and not self._stop_event.is_set():
            value = random.uniform(cfg.mouth_sync_min, cfg.mouth_sync_max)
            self.desktopet.send_parameter(cfg.mouth_sync_parameter, value)
            self._stop_event.wait(cfg.mouth_sync_interval_ms / 1000.0)
