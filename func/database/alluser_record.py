# -*- coding: utf-8 -*-
# func/database/alluser_record.py
# 所有用户消息记录：仅记录 user 消息，按用户名标注，累计 N 条后滚动 last/past_1

import os
import re
import json
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.config import CatLearnConfig


@singleton
class CatLearnAllUserRecord:
    """所有用户消息记录器（单例）

    - 仅记录 user 消息，格式为 "[用户名]消息内容"（一条一行）；
    - 保存至 .temp/database/alluser_record.json；
    - 内部保留 rounds 轮（默认 last / past_1），达到 max_messages 条触发滚动：
      丢弃最旧一轮 → last 下移为 past_1 → 新 last 重新累积；
    - 触发滚动时返回 True，供 database_core 触发核心 search 决策。
    """

    STATE_LAST = "last"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CatLearnConfig()
        self.path = os.path.join(".temp", "database", "alluser_record.json")
        self._lock = threading.Lock()

    @staticmethod
    def _safe_name(username: str) -> str:
        """清洗用户名为可读文本（去除换行等，避免破坏行结构）"""
        if not username:
            return "匿名"
        name = re.sub(r'[\r\n\t]', ' ', str(username))
        return name.strip() or "匿名"

    def _read(self) -> dict:
        """读取 json，返回 {'last': {...}, 'past_1': {...}, ...}（缺失返回空 dict）"""
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            self.log.exception("读取 alluser_record.json 失败")
            return {}

    def _write(self, data: dict):
        """写入 json（自动创建目录）"""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入 alluser_record.json 失败")

    @classmethod
    def _round_state(cls, level: int) -> str:
        """轮次状态名：0 -> last, 1 -> past_1, 2 -> past_2 ..."""
        if level == 0:
            return cls.STATE_LAST
        return f"past_{level}"

    def record_user_message(self, username: str, text: str) -> bool:
        """记录一条 user 消息，返回是否触发滚动（触发则调用方应发起核心 search 决策）

        round 计数持久化在 json 顶部的 "round" 字段（重启后持续，不归零）。
        """
        if not text or not text.strip():
            return False
        line = f"[{self._safe_name(username)}]{text.strip()}"
        with self._lock:
            data = self._read()
            # 先读 round 计数（此时 last 还未追加本条，兼容旧文件按行数估算）
            count = self._load_count(data) + 1

            # 追加到 last 文本
            last_text = ""
            last = data.get(self.STATE_LAST)
            if isinstance(last, dict):
                last_text = str(last.get("text", "") or "")
            if last_text:
                last_text += "\n" + line
            else:
                last_text = line
            data[self.STATE_LAST] = {"state": self.STATE_LAST, "text": last_text}

            rolled = False
            if count >= self.config.record_max_messages:
                data = self._roll(data)
                count = 0
                rolled = True
            data["round"] = count
            self._write(data)
            return rolled

    @classmethod
    def _load_count(cls, data: dict) -> int:
        """从文件读取 round 计数；兼容旧文件（无 round 字段时按 last 行数估算）"""
        r = data.get("round")
        if isinstance(r, int) and r >= 0:
            return r
        last = data.get(cls.STATE_LAST)
        if isinstance(last, dict):
            text = str(last.get("text", "") or "")
            if text.strip():
                return text.count("\n") + 1
        return 0

    def _roll(self, data: dict) -> dict:
        """滚动：丢弃最旧一轮，last 下移为 past_1，其余 past 依次下移，新 last 置空"""
        rounds = max(1, self.config.record_rounds)
        # 旧 last 文本
        last = data.get(self.STATE_LAST)
        last_text = ""
        if isinstance(last, dict):
            last_text = str(last.get("text", "") or "")

        new_data = {}
        # 历史轮依次下移：new past_{level} = 旧 past_{level-1}
        for level in range(1, rounds):
            state = self._round_state(level)
            if level == 1:
                new_text = last_text
            else:
                prev_state = self._round_state(level - 1)
                prev = data.get(prev_state)
                new_text = ""
                if isinstance(prev, dict):
                    new_text = str(prev.get("text", "") or "")
            if new_text:
                new_data[state] = {"state": state, "text": new_text}
        # 新的 last 置空（重新累积）
        new_data[self.STATE_LAST] = {"state": self.STATE_LAST, "text": ""}
        return new_data

    def current_text(self) -> str:
        """返回当前 last 文本（供 search 决策使用）"""
        data = self._read()
        last = data.get(self.STATE_LAST)
        if isinstance(last, dict):
            return str(last.get("text", "") or "")
        return ""

    def full_text(self) -> str:
        """返回全部轮次文本（last + past_1 + ...），按时间从旧到新拼接"""
        data = self._read()
        rounds = max(1, self.config.record_rounds)
        parts = []
        # 从最旧到最新：past_{rounds-1} ... past_1 last
        for level in range(rounds - 1, -1, -1):
            state = self._round_state(level)
            item = data.get(state)
            if isinstance(item, dict):
                t = str(item.get("text", "") or "").strip()
                if t:
                    parts.append(t)
        return "\n".join(parts)
