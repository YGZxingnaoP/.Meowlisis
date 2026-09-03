# -*- coding: utf-8 -*-
# func/vts/body_sway.py
# 身体左右摆动控制器：平滑摆动（关键帧 + 余弦插值）
#
# 思路（相比旧版“每帧随机跳变”的抖动，改为平滑）：
#   - 每 1~2 秒随机生成一个“关键帧目标”（方向/幅度沿用原配置的随机规则）；
#   - 关键帧之间按 interval_ms 用 余弦(0->1) 插值平滑过渡，端点速度为零、无突跳；
#   - 停止时沿余弦快速回正到 base，避免大角度瞬跳。

import math
import random
import threading
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.vts.config import VtsConfig
from func.vts.vts_init import VtsInit


@singleton
class VtsBodySway:
    """身体摆动：关键帧随机目标 + 余弦平滑插值，停止时平滑回正"""

    # 关键帧间隔（秒）：每 1~2s 换一个随机目标点
    KEYFRAME_MIN_SEC = 1.0
    KEYFRAME_MAX_SEC = 2.0

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = VtsConfig()
        self.vts = VtsInit()
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()
        self._last_value = None   # 最近一次实际注入值（用于平滑回正）

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
        # 先让插值线程退出，再做回正，避免两处并发发送
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        # 平滑回正：从最后注入值沿余弦快速回到 base（约 0.35s）
        cfg = self.config
        base = cfg.body_sway_base
        last = self._last_value if self._last_value is not None else base
        step = min(0.1, max(0.02, cfg.body_sway_interval_ms / 1000.0 * 0.5))
        steps = max(3, int(0.35 / step))
        for i in range(1, steps + 1):
            ratio = i / steps
            # 余弦回正：从 last 平滑降到 base
            value = base + (last - base) * (0.5 + 0.5 * math.cos(math.pi * ratio))
            self.vts.send_parameter(cfg.body_sway_parameter, value)
            self._last_value = value
            time.sleep(step)

    def _loop(self):
        cfg = self.config
        base = cfg.body_sway_base
        cur = base  # 当前关键帧起点
        while self._running and not self._stop_event.is_set():
            # 1) 生成下一个随机关键帧目标（1~2s 后到达）
            target = self._next_keyframe(cfg)
            duration = random.uniform(self.KEYFRAME_MIN_SEC, self.KEYFRAME_MAX_SEC)
            step = cfg.body_sway_interval_ms / 1000.0
            t = 0.0
            # 2) 余弦插值：从 cur 平滑移动到 target
            while t < duration and self._running and not self._stop_event.is_set():
                ratio = min(t / duration, 1.0)
                ease = 0.5 - 0.5 * math.cos(math.pi * ratio)  # 0->1 余弦缓动
                value = cur + (target - cur) * ease
                self.vts.send_parameter(cfg.body_sway_parameter, value)
                self._last_value = value
                self._stop_event.wait(step)
                t += step
            cur = target  # 到达关键帧，成为下一段起点

    def _next_keyframe(self, cfg) -> float:
        """生成下一个关键帧目标值：方向/幅度沿用原配置规则（含概率性大摆幅）"""
        base = cfg.body_sway_base
        amplitude = cfg.body_sway_amplitude
        if random.random() < cfg.body_sway_jump_probability:
            # 概率性“大摆幅”关键帧
            magnitude = random.uniform(amplitude, cfg.body_sway_jump_amplitude)
        else:
            # 常规关键帧：在 0.5~1.0 倍基准幅度间取（保证来回有可见弧线）
            magnitude = random.uniform(max(0.001, amplitude * 0.5), amplitude)
        sign = 1 if random.random() < 0.5 else -1
        return base + sign * magnitude
