# -*- coding: utf-8 -*-
# func/llm/message_builder.py
# 短期记忆管理 + 消息组装

from typing import List, Dict


class MessageBuilder:
    """短期记忆容器，负责按用户隔离保存最近 N 轮对话并组装消息列表"""

    def __init__(self, max_rounds: int = 60):
        # 短期记忆保留轮数（1 轮 = 用户消息 + 助手回复）
        self.max_rounds = max_rounds
        # 按用户名隔离的短期记忆：{username: [{"role", "content"}, ...]}
        self.history: Dict[str, List[Dict[str, str]]] = {}

    def add_user_message(self, username: str, content: str):
        """记录一条用户消息并裁剪超出轮数的历史"""
        hist = self.history.setdefault(username, [])
        hist.append({"role": "user", "content": content})
        self._trim(username)

    def add_assistant_message(self, username: str, content: str):
        """记录一条助手回复并裁剪超出轮数的历史"""
        hist = self.history.setdefault(username, [])
        hist.append({"role": "assistant", "content": content})
        self._trim(username)

    def build_messages(self, username: str, system_prompt: str, current_user_message: str) -> List[Dict[str, str]]:
        """组装完整消息：系统提示词 + 短期记忆 + 当前用户消息"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(self.history.get(username, []))
        messages.append({"role": "user", "content": current_user_message})
        return messages

    def _trim(self, username: str):
        """按配置轮数裁剪指定用户的短期记忆"""
        hist = self.history.get(username, [])
        max_msgs = self.max_rounds * 2
        if len(hist) > max_msgs:
            self.history[username] = hist[-max_msgs:]
