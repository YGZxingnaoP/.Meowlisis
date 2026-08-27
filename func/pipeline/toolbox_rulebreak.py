# -*- coding: utf-8 -*-
# func/pipeline/toolbox_rulebreak.py
# QQ 破甲审查桥接：多会话（私聊/群聊按 session_key 隔离）

import threading

from func.tools.singleton_mode import singleton


@singleton
class ToolboxRuleBreakBridge:
    """QQ rules_break 结果桥接：{session_key: explicit}，会话之间完全隔离。

    session_key 约定：
    - QQ 私聊 = qq_private:{user_id}
    - QQ 群聊 = qq_group:{group_id}
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}

    def set_explicit(self, session_key: str, explicit: bool):
        with self._lock:
            self._state[str(session_key)] = bool(explicit)

    def is_explicit(self, session_key: str) -> bool:
        with self._lock:
            return self._state.get(str(session_key), False)

    def reset(self, session_key: str):
        self.set_explicit(session_key, False)
