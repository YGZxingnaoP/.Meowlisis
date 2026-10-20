# -*- coding: utf-8 -*-
# func/llm/message_builder.py
# 短期记忆管理 + 消息组装
# 最新2轮缓存于内存，更早轮次归档到 pipeline 的 public_short_mem.json

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
        """内存缓存超出2轮时，将最旧完整轮次格式化后归档到 pipeline 短期记忆

        开头的孤立消息（如本地规则硬触发命中后没有 assistant 回复的那条 user）必须先归档掉：
        否则 _complete_rounds 从第 0 条就 break，archive_rounds 恒为负，归档永久停摆
        —— 对话只留在内存里、json 不再更新，重启即丢。
        """
        while self._starts_with_orphan():
            self._archive_item(self.history.pop(0))
        complete = self._complete_rounds(self.history)
        archive_rounds = complete - self.HISTORY_ROUNDS
        for _ in range(max(0, archive_rounds) * 2):
            self._archive_item(self.history.pop(0))

    def _starts_with_orphan(self) -> bool:
        """内存缓存开头是不是配不上对的孤立消息（不是 user→assistant 的正常一轮）

        只有 1 条时（当前轮还没回复）不算孤立，必须留在内存里等回复。
        """
        if len(self.history) < 2:
            return False
        first, second = self.history[0], self.history[1]
        if first.get("role") == "user" and second.get("role") == "assistant":
            return False
        self.log.warning(f"[短期记忆] 开头有孤立消息（role={first.get('role')}），直接归档，避免归档停摆")
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
        """把用户消息格式化为「时间+说话人+内容」的随机格式（与归档逻辑一致）

        `username` 必须是内部编号；显示名由 display_name() 这个唯一规则给出。
        """
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

    def build_messages(self, username: str, system_prompt: str, current_user_message: str) -> List[Dict[str, str]]:
        """组装完整消息：system + json旧记忆 + 内存新记忆 + 当前用户消息"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 旧记忆（json，已去掉 type，content 已格式化）
        for item in self.short_memory.load():
            messages.append({"role": item["role"], "content": item["content"]})

        # 新记忆（内存缓存，去掉内部字段）
        for item in self.history:
            messages.append({"role": item["role"], "content": item["content"]})

        messages.append({"role": "user", "content": current_user_message})
        return messages
