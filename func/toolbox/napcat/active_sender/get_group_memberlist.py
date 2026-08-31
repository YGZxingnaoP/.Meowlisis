# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/get_group_memberlist.py
# 获取群成员列表：用于识别群机器人（按昵称/群名片找 QQ 号）

from typing import List, Dict, Optional

from func.log.default_log import DefaultLog


class TBGetGroupMemberList:
    """获取指定群的成员列表，并按昵称/群名片反查 QQ 号（识别群机器人）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def get(self, group_id) -> List[dict]:
        """返回群成员列表 [{user_id, nickname, card, role}]"""
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            ret = TBNapCatCore().call_action_sync(
                "get_group_member_list", {"group_id": int(group_id)}
            )
            data = self._extract(ret)
            result = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                result.append({
                    "user_id": str(item.get("user_id", "")),
                    "nickname": str(item.get("nickname", "") or ""),
                    "card": str(item.get("card", "") or ""),
                    "role": str(item.get("role", "") or ""),
                })
            return result
        except Exception:
            self.log.exception(f"获取群成员列表失败: {group_id}")
            return []

    def find_by_name(self, group_id, name: str) -> Optional[dict]:
        """按昵称/群名片匹配群成员，返回第一个匹配（用于 @ 特定成员）。

        匹配优先级：群名片 card / QQ 昵称 nickname 精确相等 → card 包含 → nickname 包含。
        一次性拉取成员列表，避免重复调用 API。
        """
        target = str(name or "").strip()
        if not target:
            return None
        members = self.get(group_id)
        # 1) 精确匹配（群名片 card 优先于 QQ 昵称 nickname）
        for key in ("card", "nickname"):
            for m in members:
                if str(m.get(key, "") or "").strip() == target:
                    return m
        # 2) 包含匹配（同样 card 优先）
        for key in ("card", "nickname"):
            for m in members:
                if target in str(m.get(key, "") or ""):
                    return m
        return None

    @staticmethod
    def _extract(ret):
        if isinstance(ret, list):
            return ret
        if isinstance(ret, dict):
            return ret.get("data") or ret.get("members") or []
        return []

    # ==================== AI tool ====================
    def build_tools(self) -> List[dict]:
        return [{
            "type": "function",
            "function": {
                "name": "get_group_member_list",
                "description": "获取指定群的成员列表，用于识别群成员（如群机器人）的 QQ 号",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "group_id": {"type": "string", "description": "群号"},
                    },
                    "required": ["group_id"],
                },
            },
        }]

    def dispatch(self, name: str, arguments: dict) -> str:
        if name == "get_group_member_list":
            group_id = arguments.get("group_id", "")
            members = self.get(group_id)
            if not members:
                return f"未获取到群 {group_id} 的成员列表"
            lines = [
                f"{m.get('card') or m.get('nickname') or m.get('user_id')}: {m.get('user_id')} (role={m.get('role')})"
                for m in members
            ]
            return f"群 {group_id} 成员列表：\n" + "\n".join(lines)
        return f"错误：未知工具 {name}"
