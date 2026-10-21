# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/group_at.py
# 群聊 @ 工具：只指定目标成员，回复正文仍由模型自己写

from typing import List

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class TBGroupAt:
    """群聊专用 @ 工具：调用后这条回复以 @某人 的形式发出"""

    TOOL_NAME = "group_at"
    RESOLVE_LIMIT = 200

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def build_tools(self) -> List[dict]:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "在群里点名对某个成员说话。这是可选的，默认不要调用：绝大多数回复直接说就行，"
                    "只有确实要单独对某个人说话、需要他看到时才用。"
                    "调用后这条回复会以 @他的形式发出，正文照常写。"
                    "member 填群成员的群名片、昵称或 QQ 号。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "member": {"type": "string",
                                   "description": "要 @ 的群成员：群名片、昵称或 QQ 号"},
                    },
                    "required": ["member"],
                },
            },
        }]

    def resolve(self, group_id, member):
        raw = str(member or "").strip()
        if not raw:
            return None
        from func.toolbox.napcat.groupchat.get_group_record import TBGetGroupRecord
        rows = TBGetGroupRecord().members(group_id, limit=self.RESOLVE_LIMIT)
        if not rows:
            return None
        if raw.isdigit():
            for row in rows:
                if str(row.get("qq") or "") == raw:
                    return row
        for row in rows:
            if raw == str(row.get("name") or ""):
                return row
        hits = [r for r in rows if raw in str(r.get("name") or "")]
        if len(hits) == 1:
            return hits[0]
        return None

    def send(self, group_id, row, text) -> str:
        gid = str(group_id or "")
        if not gid or not row:
            return ""
        from func.toolbox.napcat.napcat_core import TBNapCatCore
        body = str(text or "").strip()
        TBNapCatCore().send_group_at_text(gid, row.get("qq"), body)
        self.log.info(f"[群聊@] @{row.get('name')}({row.get('qq')})：{body[:30]}")
        return f"已@ {row.get('name')}"
