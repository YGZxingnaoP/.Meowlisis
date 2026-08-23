# -*- coding: utf-8 -*-
# func/toolbox/add_backlog/add_backlog.py
# Add Backlog 纯执行器：追加写入 character/backlog/{username}.json，不做任何决策

import os
import json

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class TBAddBacklog:
    """待办落盘执行器：只负责把确认后的待办追加写入 backlog 文件"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.backlog_dir = os.path.join("character", "backlog")

    def add_todo(self, username: str, item: dict) -> bool:
        """追加一条待办到 character/backlog/{username}.json 的 to_do_list"""
        if not username:
            self.log.warning("[AddBacklog] username 为空，无法写入待办")
            return False
        if not isinstance(item, dict) or not item:
            return False

        path = os.path.join(self.backlog_dir, f"{username}.json")
        data = self._load(path)
        if data is None:
            data = {"username": username, "to_do_list": []}
        if not isinstance(data.get("to_do_list"), list):
            data["to_do_list"] = []
        data["to_do_list"].append(item)

        try:
            os.makedirs(self.backlog_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.log.info(f"[AddBacklog] 已写入待办 {username}: {str(item.get('content', ''))[:20]}")
            return True
        except Exception:
            self.log.exception(f"[AddBacklog] 写入待办失败: {path}")
            return False

    def _load(self, path: str):
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            self.log.exception(f"[AddBacklog] 读取待办文件失败: {path}")
            return None
