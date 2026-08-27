# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/napcat_active.py
# 群聊主动回复控制：@ 立即回复；普通消息累计到阈值后由 AI 决策是否插话（pass 可跳过有限次）

import random
import threading
from typing import Dict

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.napcat.config import TBNapCatConfig


@singleton
class TBNapCatActive:
    """群聊主动回复决策器：维护每群计数/阈值/pass 次数，返回是否回复的决策"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()
        self._lock = threading.Lock()
        # group_id -> {"count": int, "threshold": int, "pass_count": int}
        self._state: Dict[str, dict] = {}

    # ==================== 对外决策 ====================
    def on_message(self, parsed: dict) -> dict:
        """处理一条群聊消息，返回统一结构的决策 dict。

        返回结构统一为：{"action", "force", "at_self", "username"}
        action 取值：
        - skip   : 暂不回复（仅累计计数）
        - reply  : 立即回复（@ 触发，或 pass 次数用尽后强制回复）
        - decide : 达到阈值，需 AI 决策是否插话（可能输出 pass）
        """
        group_id = str(parsed.get("group_id", ""))
        at_self = bool(parsed.get("at_self"))
        is_self = bool(parsed.get("is_self"))
        username = parsed.get("username")

        # 自己发的消息不触发
        if is_self:
            return {"action": "skip", "force": False, "at_self": False, "username": None}

        # 主动回复总开关关闭时，仅 @ 触发回复
        if not self.config.group_active_enabled:
            if at_self:
                return {"action": "reply", "force": False, "at_self": True, "username": username}
            return {"action": "skip", "force": False, "at_self": False, "username": None}

        # @ 角色昵称：立即回复并重置计数
        if at_self:
            self._reset(group_id)
            return {"action": "reply", "force": False, "at_self": True, "username": username}

        # 普通消息：仅纯文本消息累计计数（纯图片/表情等无文本消息不触发主动回复）
        text = str(parsed.get("text") or "").strip()
        if not text:
            return {"action": "skip", "force": False, "at_self": False, "username": None}

        # 普通消息：累计计数（同一用户连发只算一条，换人才 +1）
        user_id = str(parsed.get("user_id") or "")
        with self._lock:
            st = self._state.setdefault(group_id, self._new_state(group_id))
            if st.get("last_user") != user_id:
                st["count"] += 1
                st["last_user"] = user_id
            if st["count"] < st["threshold"]:
                return {"action": "skip", "force": False, "at_self": False, "username": None}
            # 达到阈值
            force = st["pass_count"] >= self.config.group_pass_rounds_for(group_id)
            st["count"] = 0
            st["threshold"] = self._new_threshold(group_id)
            st["last_user"] = None
            if force:
                st["pass_count"] = 0
            action = "reply" if force else "decide"
        return {"action": action, "force": force, "at_self": False, "username": None}

    def reset_group(self, group_id: str):
        """重置某群计数（@ 触发时调用，@ 回复后主动插话重新计时）"""
        self._reset(group_id)

    # ==================== pass / 回复记录 ====================
    def record_pass(self, group_id: str):
        """AI 决策为 pass 时调用，累计一次 pass"""
        with self._lock:
            st = self._state.setdefault(str(group_id), self._new_state(str(group_id)))
            st["pass_count"] += 1

    def record_reply(self, group_id: str):
        """成功回复后调用，清零 pass 计数"""
        with self._lock:
            st = self._state.get(str(group_id))
            if st:
                st["pass_count"] = 0

    # ==================== 内部 ====================
    def _reset(self, group_id: str):
        with self._lock:
            self._state[str(group_id)] = self._new_state(str(group_id))

    def _new_state(self, group_id: str) -> dict:
        return {"count": 0, "threshold": self._new_threshold(group_id), "pass_count": 0,
                "last_user": None}

    def _new_threshold(self, group_id: str) -> int:
        """阈值 = 基数 ± jitter%，取整（随机）"""
        base = self.config.group_reply_base_for(group_id)
        jitter = self.config.group_config(group_id).get("reply_jitter", self.config.group_reply_jitter)
        try:
            jitter = float(jitter)
        except (TypeError, ValueError):
            jitter = self.config.group_reply_jitter
        low = max(1, round(base * (1 - jitter)))
        high = max(low, round(base * (1 + jitter)))
        return random.randint(low, high)
