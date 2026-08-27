# -*- coding: utf-8 -*-
# func/pipeline/msg_rulebreak.py
# 主线程破甲审查桥接：单会话（主线程天然单会话），存当前是否命中色情

import threading

from func.tools.singleton_mode import singleton


@singleton
class MsgRuleBreakBridge:
    """主线程 rules_break 结果桥接：{explicit} 单值。

    - 由 catbrain rules_break 审查后写入；
    - 由 SystemPromptBridge 构建主线程提示词时读取（读后即清，避免残留）。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._explicit = False

    def set_explicit(self, explicit: bool):
        with self._lock:
            self._explicit = bool(explicit)

    def is_explicit(self) -> bool:
        with self._lock:
            return self._explicit

    def reset(self):
        self.set_explicit(False)
