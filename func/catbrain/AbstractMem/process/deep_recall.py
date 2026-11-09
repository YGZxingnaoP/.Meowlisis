# -*- coding: utf-8 -*-
# func/catbrain/AbstractMem/process/deep_recall.py
# 深度回忆取数：摘要优先，character/memory 原文只做次级参考与按需检索

import datetime
import json
import os
from typing import List, Optional

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.catbrain.AbstractMem.load_abmem import MeowLoadAbstractMemory
from func.catbrain.AbstractMem.process.recall_index import get_index
from func.catbrain.UserMemory.load_usrmem import MeowLoadUserMemory
from func.calendar.birthday import DateBirthday
from func.pipeline.id_signup import display_name

RESULT_LIMIT = 2000


class MeowDeepRecallEvidence:
    """一次深度回忆的取数器：摘要（优先）+ 档案 + 生日 + 聊天原文（次级）"""

    def __init__(self, uid: str, query: str = "", summary_limit: int = 6,
                 raw_days: int = 7, raw_limit: int = 30):
        self.log = DefaultLog().getLogger()
        self.uid = str(uid or "")
        self.query = str(query or "").strip()
        self.summary_limit = max(1, int(summary_limit or 6))
        self.raw_days = max(1, int(raw_days or 7))
        self.raw_limit = max(1, int(raw_limit or 30))
        self.abmem = MeowLoadAbstractMemory()
        self.usrmem = MeowLoadUserMemory()
        self.birthday = DateBirthday()
        self.memory_dir = os.path.join("character", "memory")
        # 逐行检索时不要再反复查身份表
        self._name_cache = self._name()

    # ==================== 摘要（优先） ====================
    def summary(self, query: str = "", limit: int = None) -> str:
        text = str(query or self.query or "").strip()
        cap = max(1, int(limit or self.summary_limit))
        try:
            data = self.abmem.load()
            if not data:
                return ""
            index = get_index(self.abmem.meow_dir, data, self.abmem.jieba_tool)
            picked = index.recall(
                text, months=None,
                gate_ratio=float(self.abmem.config.recall_gate_ratio),
                topic="")
        except Exception:
            self.log.exception("[深度回忆] 检索摘要失败")
            return ""
        lines = [f"# {AppConfig().ai_name}的记忆摘要（优先）"]
        used = 0
        for doc_id in picked or []:
            item = index.docs.get(doc_id)
            if not isinstance(item, dict):
                continue
            try:
                lines.append(self.abmem._render(item))
            except Exception:
                continue
            used += 1
            if used >= cap:
                break
        return "\n".join(lines) if used else ""

    # ==================== 原文（次级） ====================
    def _recent_files(self, days: int) -> List[str]:
        files = []
        today = datetime.date.today()
        for offset in range(max(1, int(days))):
            day = (today - datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
            path = os.path.join(self.memory_dir, f"{day}.txt")
            if os.path.isfile(path):
                files.append(path)
        return files

    def _name(self) -> str:
        try:
            return display_name(self.uid) if self.uid else ""
        except Exception:
            return str(self.uid or "")

    def _match_line(self, line: str, keyword: str = "", require_keyword: bool = False) -> bool:
        body = str(line or "")
        if not body.strip():
            return False
        name = self._name_cache
        hit_person = bool(name and name in body) or (bool(self.uid) and f"[{self.uid}]" in body)
        hit_word = bool(keyword and keyword in body)
        if require_keyword:
            return hit_person and hit_word
        return hit_person

    def search_chat(self, keyword: str = "", days: int = None, limit: int = None) -> str:
        key = str(keyword or "").strip()
        cap = max(1, int(limit or self.raw_limit))
        rows = []
        for path in self._recent_files(days or self.raw_days):
            day = os.path.basename(path)[:10]
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.rstrip("\n")
                        if self._match_line(line, key, require_keyword=bool(key)):
                            rows.append(f"{day} {line}")
                            if len(rows) >= cap:
                                break
            except Exception:
                self.log.exception(f"[深度回忆] 读取原文失败: {path}")
            if len(rows) >= cap:
                break
        if not rows:
            return ""
        return "# 聊天原文（次级参考）\n" + "\n".join(rows[-cap:])

    def read_chat_day(self, day: str, limit: int = None) -> str:
        stamp = str(day or "").strip()
        if len(stamp) < 10:
            return ""
        path = os.path.join(self.memory_dir, f"{stamp[:10]}.txt")
        if not os.path.isfile(path):
            return ""
        cap = max(1, int(limit or self.raw_limit))
        rows = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if self._match_line(line):
                        rows.append(line)
                        if len(rows) >= cap:
                            break
        except Exception:
            self.log.exception(f"[深度回忆] 读取原文失败: {path}")
        return "\n".join(rows)

    def profile(self) -> str:
        try:
            return self.usrmem.build(self.uid) or ""
        except Exception:
            self.log.exception("[深度回忆] 读取用户档案失败")
            return ""

    def birthday_today(self) -> bool:
        try:
            return bool(self.uid) and bool(self.birthday.is_today(self.uid))
        except Exception:
            return False

    # ==================== 工具 ====================
    @staticmethod
    def build_tools() -> List[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "recall_memory",
                    "description": "检索角色对这些事的记忆摘要（优先用这个）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "要回忆的事/关键词"},
                            "limit": {"type": "integer", "description": "最多几条，默认 6"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_chat",
                    "description": "在最近几天的聊天原文里按关键词检索（摘要不够时再用）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string", "description": "关键词"},
                            "days": {"type": "integer", "description": "向前查几天，默认 7"},
                            "limit": {"type": "integer", "description": "最多几条，默认 30"},
                        },
                        "required": ["keyword"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_chat_day",
                    "description": "读取某一天里和TA有关的聊天记录（日期格式 YYYY-MM-DD）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "string", "description": "日期 YYYY-MM-DD"},
                            "limit": {"type": "integer", "description": "最多几条，默认 30"},
                        },
                        "required": ["day"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_profile",
                    "description": "读取TA的用户档案（偏好/关系/生日等）。",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def dispatch(self, name: str, arguments) -> str:
        try:
            args = json.loads(arguments or "{}") if isinstance(arguments, str) else (arguments or {})
        except Exception:
            args = {}
        if not isinstance(args, dict):
            args = {}
        try:
            if name == "recall_memory":
                out = self.summary(str(args.get("query") or ""), args.get("limit"))
            elif name == "search_chat":
                out = self.search_chat(str(args.get("keyword") or ""),
                                       args.get("days"), args.get("limit"))
            elif name == "read_chat_day":
                out = self.read_chat_day(str(args.get("day") or ""), args.get("limit"))
            elif name == "read_profile":
                out = self.profile()
            else:
                return f"错误：未知工具 {name}"
        except Exception:
            self.log.exception(f"[深度回忆] 工具执行失败: {name}")
            return f"错误：工具执行异常 {name}"
        text = str(out or "").strip()
        if not text:
            return "（没有找到相关记忆）"
        return text[:RESULT_LIMIT]
