# -*- coding: utf-8 -*-
# func/vts/desktopet/mouth_sync.py
# 桌宠嘴部同步控制器：平滑开合（关键帧 + 余弦插值）
#
# 由 TTS 播放状态驱动：播放时以较短的“关键帧”节奏（每 0.25~0.7s 随机取一个开合目标），
# 段内用余弦插值平滑过渡（不再每 90ms 随机跳变）；停止时余弦平滑闭合到 close。

import math
import random
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.vts.desktopet.config import DesktopetConfig
from func.vts.desktopet.vts_init import DesktopetInit


@singleton
class DesktopetMouthSync:
    """桌宠嘴部同步：关键帧随机开合目标 + 余弦平滑插值，停止时平滑闭合"""

    # 嘴部关键帧间隔（秒）：说话时每 0.25~0.7s 换一个开合目标（比身体快，接近语音节奏）
    KEYFRAME_MIN_SEC = 0.25
    KEYFRAME_MAX_SEC = 0.7

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = DesktopetConfig()
        self.desktopet = DesktopetInit()
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()
        self._last_value = None

    def start(self):
        """开始嘴部开合（播放时调用）"""
        if not self.config.switch or not self.config.mouth_sync_enabled:
            return
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._last_value = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止嘴部开合并平滑闭合（停止播放时调用）"""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        # 余弦平滑闭合到 close
        cfg = self.config
        close = cfg.mouth_sync_close
        last = self._last_value if self._last_value is not None else close
        step = min(0.1, max(0.02, cfg.mouth_sync_interval_ms / 1000.0 * 0.5))
        steps = max(3, int(0.3 / step))
        for i in range(1, steps + 1):
            ratio = i / steps
            value = close + (last - close) * (0.5 + 0.5 * math.cos(math.pi * ratio))
            self.desktopet.send_parameter(cfg.mouth_sync_parameter, value)
            self._last_value = value
            time.sleep(step)

    def _loop(self):
        cfg = self.config
        lo, hi = cfg.mouth_sync_min, cfg.mouth_sync_max
        cur = cfg.mouth_sync_close  # 从闭合开始
        while self._running and not self._stop_event.is_set():
            target = random.uniform(lo, hi)  # 开合目标（保持原取值域）
            duration = random.uniform(self.KEYFRAME_MIN_SEC, self.KEYFRAME_MAX_SEC)
            step = cfg.mouth_sync_interval_ms / 1000.0
            t = 0.0
            while t < duration and self._running and not self._stop_event.is_set():
                ratio = min(t / duration, 1.0)
                ease = 0.5 - 0.5 * math.cos(math.pi * ratio)  # 0->1 余弦缓动
                value = cur + (target - cur) * ease
                self.desktopet.send_parameter(cfg.mouth_sync_parameter, value)
                self._last_value = value
                self._stop_event.wait(step)
                t += step
            cur = target
