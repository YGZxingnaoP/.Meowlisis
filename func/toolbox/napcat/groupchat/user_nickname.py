# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/user_nickname.py
# 群聊 QQ 号 ↔ 昵称（用户档案昵称）映射工具：供 @ 触发时解析稳定用户档案昵称

import os
import json
import threading
from typing import Optional

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class TBUserNicknameMap:
    """维护 QQ 号与昵称（含用户档案昵称）的映射，落盘到 .NapCat/user_nickname_map.json

    优先级：profile_name（手动绑定/稳定的用户档案昵称） > card（群名片） > nickname（QQ 昵称）
    """

    MAP_PATH = os.path.join(".NapCat", "user_nickname_map.json")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.Lock()
        self._map: dict = {}
        self._load()

    # ==================== 落盘 ====================
    def _load(self):
        try:
            if os.path.exists(self.MAP_PATH):
                with open(self.MAP_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._map = data
        except Exception:
            self.log.exception("读取 QQ 昵称映射失败")

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.MAP_PATH), exist_ok=True)
            with open(self.MAP_PATH, "w", encoding="utf-8") as f:
                json.dump(self._map, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("保存 QQ 昵称映射失败")

    # ==================== 写入 ====================
    def observe(self, user_id, card: str = "", nickname: str = ""):
        """从群消息 sender 顺带记录昵称（不覆盖已手动绑定的 profile_name）"""
        uid = str(user_id or "").strip()
        if not uid:
            return
        with self._lock:
            item = self._map.get(uid) or {}
            if card and str(card).strip():
                item["card"] = str(card).strip()
            if nickname and str(nickname).strip():
                item["nickname"] = str(nickname).strip()
            # 首次出现时，若没有 profile_name，则用 card/nickname 作为默认档案昵称
            if not item.get("profile_name"):
                default = item.get("card") or item.get("nickname") or ""
                if default:
                    item["profile_name"] = default
            self._map[uid] = item
            self._save()

    def bind(self, user_id, profile_name: str):
        """手动绑定 QQ 号到用户档案昵称（profile_name）"""
        uid = str(user_id or "").strip()
        name = str(profile_name or "").strip()
        if not uid or not name:
            return False
        with self._lock:
            item = self._map.get(uid) or {}
            item["profile_name"] = name
            self._map[uid] = item
            self._save()
        return True

    # ==================== 查询 ====================
    def resolve(self, user_id) -> str:
        """按 QQ 号解析昵称：profile_name > card > nickname > 返回原 QQ 号"""
        uid = str(user_id or "").strip()
        if not uid:
            return ""
        item = self._map.get(uid) or {}
        return (item.get("profile_name") or item.get("card") or item.get("nickname") or uid).strip()

    def reverse(self, name: str) -> Optional[str]:
        """按昵称（profile_name/card/nickname）反查 QQ 号"""
        target = str(name or "").strip()
        if not target:
            return None
        for uid, item in self._map.items():
            if target in (item.get("profile_name"), item.get("card"), item.get("nickname")):
                return uid
        return None

    def all(self) -> dict:
        """返回完整映射（供 AI 查询）"""
        with self._lock:
            return dict(self._map)

    # ==================== AI tool ====================
    def build_tools(self):
        """供父级 toolcalls 注册的昵称映射工具"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "bind_qq_nickname",
                    "description": "把某个 QQ 号绑定到用户档案昵称（用户档案按昵称存取时使用）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "string", "description": "QQ 号"},
                            "profile_name": {"type": "string", "description": "用户档案昵称"},
                        },
                        "required": ["user_id", "profile_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_qq_nickname_map",
                    "description": "查看当前 QQ 号与昵称（用户档案昵称）的映射关系",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def dispatch(self, name: str, arguments: dict) -> str:
        if name == "bind_qq_nickname":
            ok = self.bind(arguments.get("user_id", ""), arguments.get("profile_name", ""))
            return f"绑定成功：{arguments.get('user_id')} -> {arguments.get('profile_name')}" if ok else "绑定失败"
        if name == "get_qq_nickname_map":
            data = self.all()
            if not data:
                return "暂无昵称映射"
            lines = [f"{uid} -> {item.get('profile_name') or item.get('card') or item.get('nickname') or uid}"
                     for uid, item in data.items()]
            return "昵称映射：\n" + "\n".join(lines)
        return f"错误：未知工具 {name}"
