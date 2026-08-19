# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/sender.py
# 主动发送框架：发送消息 / 发送文件（受 toolcalls 控制，后续完善）

from typing import List, Dict

from func.log.default_log import DefaultLog
from func.toolbox.napcat.active_sender.get_friendlist import TBGetFriendList
from func.toolbox.napcat.active_sender.get_grouplist import TBGetGroupList


class TBSender:
    """主动发送工具框架：提供 tool schema 与基础发送实现"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.get_friendlist = TBGetFriendList()
        self.get_grouplist = TBGetGroupList()

    # ==================== tool schema ====================
    def build_tools(self) -> List[Dict]:
        """返回主动发送工具 schema（发送消息 / 发送文件）"""
        target_type = {"type": "string", "enum": ["friend", "group"],
                       "description": "目标类型：friend 好友 / group 群聊"}
        return [
            {
                "type": "function",
                "function": {
                    "name": "send_qq_message",
                    "description": "通过 QQ 给指定好友或群聊主动发送文本消息",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_type": target_type,
                            "target_id": {"type": "string", "description": "目标 QQ 号或群号"},
                            "text": {"type": "string", "description": "要发送的文本内容"},
                        },
                        "required": ["target_type", "target_id", "text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_qq_file",
                    "description": "通过 QQ 给指定好友或群聊主动发送文件",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_type": target_type,
                            "target_id": {"type": "string", "description": "目标 QQ 号或群号"},
                            "file_path": {"type": "string", "description": "本地文件绝对路径"},
                        },
                        "required": ["target_type", "target_id", "file_path"],
                    },
                },
            },
        ]

    # ==================== 执行分发 ====================
    def dispatch(self, name: str, arguments: Dict) -> str:
        """按工具名执行主动发送"""
        if name == "send_qq_message":
            return self.send_text(
                arguments.get("target_type"),
                arguments.get("target_id"),
                arguments.get("text", ""),
            )
        if name == "send_qq_file":
            return self.send_file(
                arguments.get("target_type"),
                arguments.get("target_id"),
                arguments.get("file_path", ""),
            )
        return f"错误：未知工具 {name}"

    # ==================== 基础发送 ====================
    def send_text(self, target_type: str, target_id, text: str) -> str:
        """发送文本（框架实现，返回结果说明）"""
        if not text or not target_id:
            return "发送失败：缺少目标或内容"
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            core = TBNapCatCore()
            action = "send_group_msg" if target_type == "group" else "send_private_msg"
            key = "group_id" if target_type == "group" else "user_id"
            ret = core.call_action_sync(action, {
                key: int(target_id),
                "message": [{"type": "text", "data": {"text": text}}],
            })
            return f"已发送：{text[:30]}"
        except Exception:
            self.log.exception("主动发送文本失败")
            return "发送失败"

    def send_file(self, target_type: str, target_id, file_path: str) -> str:
        """发送文件（框架实现，返回结果说明）"""
        if not file_path or not target_id:
            return "发送失败：缺少目标或文件路径"
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            core = TBNapCatCore()
            action = "send_group_msg" if target_type == "group" else "send_private_msg"
            key = "group_id" if target_type == "group" else "user_id"
            ret = core.call_action_sync(action, {
                key: int(target_id),
                "message": [{"type": "file", "data": {"file": file_path}}],
            })
            return f"已发送文件：{file_path}"
        except Exception:
            self.log.exception("主动发送文件失败")
            return "发送失败"
