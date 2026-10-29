# -*- coding: utf-8 -*-
# func/llm_active/director/copied/message_builder.py
# 【复制件】短期记忆管理 + 消息组装
# 来源：func/llm/message_builder.py（逐字复制，额外加 flush_all / build_context）
# 最新2轮缓存于内存，更早轮次归档到 pipeline 的 public_short_mem.json
# 纪律：本文件不 import func/llm/**，主链路改动时必须两边同步。

import datetime
import random
from typing import List, Dict

from func.log.default_log import DefaultLog
from func.pipeline.short_memory import ShortMemory


class MessageBuilder:
    """短期记忆容器：最新2轮内存缓存，旧轮次归档，组装时 json + 缓存 + 当前消息拼接"""

    # 内存缓存保留的最新轮数
    HISTORY_ROUNDS = 2

    # 用户消息归档时的随机格式（防 AI 因格式惯性输出）
    USER_FORMATS = [
        "{time}，{name}，{content}",
        "{name}于{time}，{content}",
        "{content}，{time}，{name}",
        "{content}，{name}",
        "{name}，{content}",
    ]

    def __init__(self, max_rounds: int = 60):
        self.log = DefaultLog().getLogger()
        # 短期记忆总轮数（含内存缓存的2轮）
        self.max_rounds = max_rounds
        # json 归档上限轮数（总轮数减2）
        self.json_max_rounds = max(0, max_rounds - self.HISTORY_ROUNDS)
        # 短期记忆桥接（负责 json 收发）
        self.short_memory = ShortMemory()
        # 最新轮次内存缓存（内部多存 speaker/time，仅用于格式化，不发送）
        self.history: List[Dict[str, str]] = []

    def set_max_rounds(self, max_rounds: int):
        """配置热重载：更新短期记忆总轮数，并联动 json 归档上限"""
        self.max_rounds = int(max_rounds)
        self.json_max_rounds = max(0, self.max_rounds - self.HISTORY_ROUNDS)

    def flush_all(self):
        """把内存里的全部轮次归档到 json 并清空内存缓存（导演退出时对齐顺序）"""
        while self.history:
            self._archive_item(self.history.pop(0))
        self.history = []

    @staticmethod
    def _now() -> str:
        """返回当前日期时间（如 2026-10-14 14:23）"""
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    def add_user_message(self, username: str, content: str):
        """记录一条用户消息到内存缓存（含说话人与时间），并尝试归档旧轮次"""
        self.history.append({
            "role": "user",
            "content": content,
            "speaker": username,
            "time": self._now(),
            "type": "llm_fast_response",
        })
        self._flush()

    def add_assistant_message(self, username: str, content: str, ai_name: str = "AI"):
        """记录一条助手回复到内存缓存（含 AI 名与时间），并尝试归档旧轮次"""
        self.history.append({
            "role": "assistant",
            "content": content,
            "speaker": ai_name,
            "time": self._now(),
            "type": "llm_fast_response",
        })
        self._flush()

    def _flush(self):
        """内存缓存超出2轮时，将最旧完整轮次格式化后归档到 pipeline 短期记忆"""
        while self._starts_with_orphan():
            self._archive_item(self.history.pop(0))
        complete = self._complete_rounds(self.history)
        archive_rounds = complete - self.HISTORY_ROUNDS
        for _ in range(max(0, archive_rounds) * 2):
            self._archive_item(self.history.pop(0))

    def _starts_with_orphan(self) -> bool:
        """内存缓存开头是不是配不上对的孤立消息"""
        if len(self.history) < 2:
            return False
        first, second = self.history[0], self.history[1]
        if first.get("role") == "user" and second.get("role") == "assistant":
            return False
        self.log.warning(f"[导演短期记忆] 开头有孤立消息（role={first.get('role')}），直接归档")
        return True

    def _archive_item(self, item: Dict):
        """把一条内存缓存格式化后写入 json 短期记忆"""
        formatted = self._format_item(item)
        self.short_memory.save({
            "role": item["role"],
            "content": formatted,
            "type": item.get("type", "llm_fast_response"),
        }, self.json_max_rounds)

    @staticmethod
    def format_user_content(username: str, content: str) -> str:
        """把用户消息格式化为「时间+说话人+内容」的随机格式（与归档逻辑一致）"""
        now = MessageBuilder._now()
        from func.pipeline.id_signup import display_name
        name = display_name(username)
        text = str(content or "")
        fmt = random.choice(MessageBuilder.USER_FORMATS)
        return fmt.format(time=now, name=name, content=text)

    def _format_item(self, item: Dict) -> str:
        """归档时仅用户消息做随机格式，助手消息原样保留内容"""
        if item.get("role") == "user":
            return self.format_user_content(item.get("speaker"), item.get("content"))
        return item.get("content", "")

    @staticmethod
    def _complete_rounds(items: List[Dict]) -> int:
        """计算列表开头完整轮数（user 后紧跟 assistant 为一轮）"""
        rounds = 0
        i = 0
        while i + 1 < len(items):
            if items[i].get("role") == "user" and items[i + 1].get("role") == "assistant":
                rounds += 1
                i += 2
            else:
                break
        return rounds

    def build_context(self, system_prompt: str) -> List[Dict[str, str]]:
        """组装上下文（无当前用户消息）：system + json旧记忆 + 内存新记忆

        导演的主动开口（没有用户消息的那一轮）用这个，不伪造一条 user。
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for item in self.short_memory.load():
            messages.append({"role": item["role"], "content": item["content"]})
        for item in self.history:
            messages.append({"role": item["role"], "content": item["content"]})
        return messages

    def build_messages(self, username: str, system_prompt: str,
                       current_user_message: str) -> List[Dict[str, str]]:
        """组装完整消息：system + json旧记忆 + 内存新记忆 + 当前用户消息"""
        messages = self.build_context(system_prompt)
        messages.append({"role": "user", "content": current_user_message})
        return messages
