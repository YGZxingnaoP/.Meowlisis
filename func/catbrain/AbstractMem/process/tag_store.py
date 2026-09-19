# -*- coding: utf-8 -*-
import os
import json
import threading
from typing import List

from func.log.default_log import DefaultLog


class MeowTagStore:
    """tag 存储类"""

    def __init__(self):
        """指定 tags.json 路径并初始化写锁"""
        self.log = DefaultLog().getLogger()
        self.path = os.path.join("character", "abstract_memory", "tags", "tags.json")
        self._lock = threading.Lock()

    def load(self) -> List[str]:
        """读取已有 tag 列表"""
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            self.log.exception("读取 tags.json 失败")
            return []

    def append(self, new_tags: List[str]):
        """去重追加新 tag 并持久化"""
        if not new_tags:
            return
        with self._lock:
            existing = self.load()
            for t in new_tags:
                t = str(t).strip()
                if t and t not in existing:
                    existing.append(t)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(existing, f, ensure_ascii=False, indent=2)
            except Exception:
                self.log.exception("写入 tags.json 失败")
