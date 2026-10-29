# -*- coding: utf-8 -*-
# func/pipeline/llm_timer.py
# LLM 活动 → 主动回复计时器 桥接

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class LLMTimerBridge:
    """LLM 活动桥接：传递 llm 是否收到消息/完成回复，触发主动回复计时器重置。

    - register：主注册位（主动回复计时器用），保持原有覆盖语义；
    - subscribe：追加订阅（导演判官用），不会顶掉主注册位；
    - notify_ai_reply(source)：带来源，弹幕等非主链路来源由订阅者自行过滤。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._on_user_message = None
        self._on_ai_reply = None
        self._subs = []

    def register(self, on_user_message=None, on_ai_reply=None):
        """注册回调：llm 收到用户消息 / 完成回复时触发（覆盖同名回调）"""
        if on_user_message:
            self._on_user_message = on_user_message
        if on_ai_reply:
            self._on_ai_reply = on_ai_reply

    def subscribe(self, on_user_message=None, on_ai_reply=None):
        """追加订阅：与 register 的主回调同时收到通知（不会覆盖）"""
        if on_user_message is None and on_ai_reply is None:
            return
        self._subs.append({"user": on_user_message, "reply": on_ai_reply})

    def notify_user_message(self):
        """llm 收到用户消息"""
        if self._on_user_message:
            self._call(self._on_user_message)
        for sub in list(self._subs):
            cb = sub.get("user")
            if cb:
                self._call(cb)

    def notify_ai_reply(self, source="llm"):
        """llm 完成回复（source：llm / danmaku / toolbox …）"""
        if self._on_ai_reply:
            self._call(self._on_ai_reply, source)
        for sub in list(self._subs):
            cb = sub.get("reply")
            if cb:
                self._call(cb, source)

    def _call(self, cb, *args):
        """单个回调异常不影响其它订阅者"""
        try:
            cb(*args)
        except Exception:
            self.log.exception("[计时桥] 回调异常")
