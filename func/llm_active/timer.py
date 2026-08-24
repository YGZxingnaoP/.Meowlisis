# -*- coding: utf-8 -*-
# func/llm_active/timer.py
# 主动回复空闲计时器

import random
import time


class AutoTimer:
    """空闲计时器：等待时长为 cold_time * random(0.8, 1.2)，重置时重新抽取随机数"""

    def __init__(self, cold_time):
        self.cold_time = cold_time
        self._deadline = 0.0
        self._paused = False
        self._pause_start = 0.0
        self.reset()

    def reset(self):
        """重置计时器：重新计算等待时长与到期时间"""
        wait = self.cold_time * random.uniform(0.8, 1.2)
        self._deadline = time.time() + wait

    def is_due(self):
        """是否已到期（暂停期间永不到期）"""
        if self._paused:
            return False
        return time.time() >= self._deadline

    def pause(self):
        """暂停计时：记录暂停起点"""
        if self._paused:
            return
        self._paused = True
        self._pause_start = time.time()

    def resume(self):
        """恢复计时：把暂停时长顺延到到期时间"""
        if not self._paused:
            return
        elapsed = time.time() - self._pause_start
        self._deadline += elapsed
        self._paused = False
