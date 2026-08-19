# -*- coding: utf-8 -*-
# func/pipeline/llm_timer.py
# LLM 活动 → 主动回复计时器 桥接

from func.tools.singleton_mode import singleton


@singleton
class LLMTimerBridge:
    """LLM 活动桥接：传递 llm 是否收到消息/完成回复，触发主动回复计时器重置"""

    def __init__(self):
        self._on_user_message = None
        self._on_ai_reply = None

    def register(self, on_user_message=None, on_ai_reply=None):
        """注册回调：llm 收到用户消息 / 完成回复时触发"""
        if on_user_message:
            self._on_user_message = on_user_message
        if on_ai_reply:
            self._on_ai_reply = on_ai_reply

    def notify_user_message(self):
        """llm 收到用户消息"""
        if self._on_user_message:
            self._on_user_message()

    def notify_ai_reply(self):
        """llm 完成回复"""
        if self._on_ai_reply:
            self._on_ai_reply()
