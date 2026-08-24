# -*- coding: utf-8 -*-
# func/vts/body_sway.py
# 身体左右摆动控制器：说话时随机抖动（活泼跳跃感）

import random
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.vts.config import VtsConfig
from func.vts.vts_init import VtsInit


@singleton
class VtsBodySway:
    """身体摆动：后台线程按周期发送随机参数值，停止时回正"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = VtsConfig()
        self.vts = VtsInit()
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()

    def start(self):
        """开始摆动（说话时调用）"""
        if not self.config.switch or not self.config.body_sway_enabled:
            return
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止摆动并回正（停止说话时调用）"""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        # 回正
        self.vts.send_parameter(self.config.body_sway_parameter, self.config.body_sway_base)

    def _loop(self):
        cfg = self.config
        while self._running and not self._stop_event.is_set():
            value = self._next_value(cfg)
            self.vts.send_parameter(cfg.body_sway_parameter, value)
            self._stop_event.wait(cfg.body_sway_interval_ms / 1000.0)

    def _next_value(self, cfg) -> float:
        """生成下一帧摆动值：常规随机 + 概率性跳跃尖峰"""
        base = cfg.body_sway_base
        amplitude = cfg.body_sway_amplitude
        # 概率性跳跃：在幅度与跳跃幅度之间取更大位移，方向随机
        if random.random() < cfg.body_sway_jump_probability:
            sign = 1 if random.random() < 0.5 else -1
            magnitude = random.uniform(amplitude, cfg.body_sway_jump_amplitude)
            return base + sign * magnitude
        return base + random.uniform(-amplitude, amplitude)
