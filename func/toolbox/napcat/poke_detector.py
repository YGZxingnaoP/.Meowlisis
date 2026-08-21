# -*- coding: utf-8 -*-
# func/toolbox/napcat/poke_detector.py
# 戳一戳检测：连续被戳 N 次触发；中间有任何消息打断则重新计数
# 通用计数器：私聊与群聊共用，message_type 区分阈值（不拆类）

import time
import threading
from typing import Optional

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.napcat.config import TBNapCatConfig


@singleton
class TBPokeDetector:
    """戳一戳检测器：连续被戳计数，任何消息打断则重置。

    - 仅内存计数，不写文件；
    - 超过冷却时间未再被戳，计数归零；
    - 中间有任何消息（文本/图片等）打断，计数归零；
    - 达到触发阈值后重置计数，避免连续刷屏。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()
        self._lock = threading.Lock()
        # 会话级计数：{ key : {count, last_time} }
        self._state = {}

    @staticmethod
    def _key(message_type: str, target_id: str) -> str:
        return f"{message_type}:{target_id}"

    def on_poke(self, message_type: str, target_id: str, user_id: str = "") -> bool:
        """收到一次戳一戳，累计计数；返回是否触发发牢骚（达到阈值返回 True）

        群聊阈值 poke_group_trigger（默认5），私聊阈值 poke_private_trigger（默认1）。
        """
        if not self.config.poke_enabled:
            return False
        threshold = self.config.poke_group_trigger if message_type == "group" else self.config.poke_private_trigger
        key = self._key(message_type, target_id)
        now = time.time()
        with self._lock:
            st = self._state.get(key)
            if st is None or (now - st["last_time"]) > self.config.poke_cooldown:
                st = {"count": 0, "last_time": now}
            st["count"] += 1
            st["last_time"] = now
            self._state[key] = st
            count = st["count"]
            if count >= threshold:
                self._state[key] = {"count": 0, "last_time": now}
                self.log.info(f"[戳一戳] 连续被戳 {count} 次，触发发牢骚（阈值 {threshold}）")
                return True
            self.log.info(f"[戳一戳] 累计被戳 {count} 次（阈值 {threshold}）")
            return False

    def on_interrupt(self, message_type: str, target_id: str):
        """有消息打断（非戳一戳）时调用，重置该会话的戳一戳计数"""
        key = self._key(message_type, target_id)
        with self._lock:
            if key in self._state:
                self.log.info("[戳一戳] 收到消息打断，重置计数")
                self._state.pop(key, None)

    def reset(self, message_type: str, target_id: str):
        """手动重置某会话的戳一戳计数"""
        key = self._key(message_type, target_id)
        with self._lock:
            self._state.pop(key, None)
