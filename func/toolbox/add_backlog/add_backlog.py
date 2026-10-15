# -*- coding: utf-8 -*-
# func/toolbox/add_backlog/add_backlog.py
# Add Backlog 纯执行器：追加写入 character/backlog/{meowid}.json，不做任何决策

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

    def add_todo(self, meowid: str, item: dict) -> bool:
        """追加一条待办（有编号就写进编号目录的 backlog.json）"""
        if not meowid:
            self.log.warning("[AddBacklog] meowid 为空，无法写入待办")
            return False
        if not isinstance(item, dict) or not item:
            return False

        from func.pipeline.id_signup import IdSignupBridge
        bridge = IdSignupBridge()
        data = bridge.read_backlog(meowid) or {"meowid": meowid, "to_do_list": []}
        if not isinstance(data.get("to_do_list"), list):
            data["to_do_list"] = []
        data["meowid"] = data.get("meowid") or meowid
        data["to_do_list"].append(item)

        try:
            path = bridge.save_backlog(meowid, data)
            self.log.info(f"[AddBacklog] 已写入待办 {meowid}: {str(item.get('content', ''))[:20]}")
            return True
        except Exception:
            self.log.exception(f"[AddBacklog] 写入待办失败: {meowid}")
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
