# -*- coding: utf-8 -*-
# func/catbrain/CatValues/values_timer.py
# 价值观 12 小时累计计时器：按真实经过时长累计，中断后从 .temp 恢复继续累计

import os
import json
import time
import threading

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.CatValues.start_update import MeowStartValuesUpdate


class MeowValuesTimer:
    """价值观计时器：按真实经过时长累计运行时间，达到 12 小时触发更新并结转溢出"""

    TIMER_PATH = os.path.join(".temp", "values_timer.json")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.starter = MeowStartValuesUpdate()
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        """启动计时器后台线程（重复调用安全）"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.log.info("价值观 12 小时累计计时器已启动")

    def stop(self):
        """停止计时器（程序退出时调用，状态已持久化）"""
        self._stop_event.set()

    def _run(self):
        """计时主循环：按真实经过时长累计，达到阈值触发更新并结转溢出"""
        interval = self.config.values_timer_check_seconds
        threshold = self.config.values_update_interval_hours * 3600
        while not self._stop_event.is_set():
            now = time.time()
            state = self._load_state()
            # 首次启动或旧状态无时间戳时，从当前时刻起算，避免一启动就累加一个间隔
            last = state.get("last_tick", 0.0) or now
            elapsed = max(0.0, now - last)
            accumulated = state.get("accumulated_seconds", 0.0) + elapsed
            if accumulated >= threshold:
                # 触发后保留溢出时长，避免已运行时间被直接清零丢失
                self._save_state(accumulated - threshold, now)
                self.log.info("价值观累计运行达到 12 小时，触发更新")
                self.starter.start_async("12小时累计计时触发")
            else:
                self._save_state(accumulated, now)
            self._stop_event.wait(interval)

    def _load_state(self) -> dict:
        """读取计时状态（程序重启后延续累计时长，兼容旧字符串时间戳）"""
        if not os.path.exists(self.TIMER_PATH):
            return {"accumulated_seconds": 0.0, "last_tick": 0.0}
        try:
            with open(self.TIMER_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            accumulated = data.get("accumulated_seconds", 0)
            try:
                accumulated = float(accumulated)
            except (TypeError, ValueError):
                accumulated = 0.0
            last = data.get("last_tick", 0)
            try:
                last = float(last)
            except (TypeError, ValueError):
                last = 0.0
            return {"accumulated_seconds": accumulated, "last_tick": last}
        except Exception:
            self.log.exception("读取价值观计时状态失败")
            return {"accumulated_seconds": 0.0, "last_tick": 0.0}

    def _save_state(self, accumulated: float, now: float):
        """保存计时状态到 .temp（含时间戳，便于下次按真实时长累计）"""
        try:
            os.makedirs(os.path.dirname(self.TIMER_PATH), exist_ok=True)
            with open(self.TIMER_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "accumulated_seconds": round(float(accumulated), 3),
                    "last_tick": now,
                    "last_tick_readable": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("保存价值观计时状态失败")
