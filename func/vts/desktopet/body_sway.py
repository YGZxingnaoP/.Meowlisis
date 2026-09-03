# -*- coding: utf-8 -*-
# func/vts/desktopet/body_sway.py
# 桌宠身体左右摆动控制器：平滑摆动（关键帧 + 余弦插值）
#
# 与 func/vts/body_sway.py 同构：每 1~2 秒随机生成关键帧目标，
# 段内按 interval_ms 用余弦 0->1 插值平滑过渡；停止时余弦平滑回正。

import math
import random
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.vts.desktopet.config import DesktopetConfig
from func.vts.desktopet.vts_init import DesktopetInit


@singleton
class DesktopetBodySway:
    """桌宠身体摆动：关键帧随机目标 + 余弦平滑插值，停止时平滑回正"""

    # 关键帧间隔（秒）：每 1~2s 换一个随机目标点
    KEYFRAME_MIN_SEC = 1.0
    KEYFRAME_MAX_SEC = 2.0

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = DesktopetConfig()
        self.desktopet = DesktopetInit()
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()
        self._last_value = None

    def start(self):
        """开始摆动（说话时调用）"""
        if not self.config.switch or not self.config.body_sway_enabled:
            return
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._last_value = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止摆动并平滑回正（停止说话时调用）"""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        # 余弦平滑回正到 base
        cfg = self.config
        base = cfg.body_sway_base
        last = self._last_value if self._last_value is not None else base
        step = min(0.1, max(0.02, cfg.body_sway_interval_ms / 1000.0 * 0.5))
        steps = max(3, int(0.35 / step))
        for i in range(1, steps + 1):
            ratio = i / steps
            value = base + (last - base) * (0.5 + 0.5 * math.cos(math.pi * ratio))
            self.desktopet.send_parameter(cfg.body_sway_parameter, value)
            self._last_value = value
            time.sleep(step)

    def _loop(self):
        cfg = self.config
        base = cfg.body_sway_base
        cur = base
        while self._running and not self._stop_event.is_set():
            target = self._next_keyframe(cfg)
            duration = random.uniform(self.KEYFRAME_MIN_SEC, self.KEYFRAME_MAX_SEC)
            step = cfg.body_sway_interval_ms / 1000.0
            t = 0.0
            while t < duration and self._running and not self._stop_event.is_set():
                ratio = min(t / duration, 1.0)
                ease = 0.5 - 0.5 * math.cos(math.pi * ratio)  # 0->1 余弦缓动
                value = cur + (target - cur) * ease
                self.desktopet.send_parameter(cfg.body_sway_parameter, value)
                self._last_value = value
                self._stop_event.wait(step)
                t += step
            cur = target

    def _next_keyframe(self, cfg) -> float:
        """生成下一个关键帧目标值：方向/幅度沿用原配置规则（含概率性大摆幅）"""
        base = cfg.body_sway_base
        amplitude = cfg.body_sway_amplitude
        if random.random() < cfg.body_sway_jump_probability:
            magnitude = random.uniform(amplitude, cfg.body_sway_jump_amplitude)
        else:
            magnitude = random.uniform(max(0.001, amplitude * 0.5), amplitude)
        sign = 1 if random.random() < 0.5 else -1
        return base + sign * magnitude
