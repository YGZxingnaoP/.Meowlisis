# -*- coding: utf-8 -*-
# func/toolbox/napcat/active_sender/module.py
# NapCat 主动发送模块：父级 toolcalls 的统一入口（内部完成选目标→拟消息→发送完整流程）

from typing import List, Dict

from func.log.default_log import DefaultLog
from func.toolbox.napcat.active_sender.single_send import TBSingleSend
from func.toolbox.napcat.active_sender.group_send import TBGroupSend


class TBNapcatActiveModule:
    """NapCat 主动发送模块入口：父级只暴露这一个工具。

    内部根据 target_type 分发到好友单发 / 群发，各自完成「选目标→拟消息→发送」完整流程。
    底层子工具（send_qq_message、search_file、get_friend_list 等）不暴露给父级，
    仅在模块内部流程中被使用。
    """

    TOOL_NAME = "napcat_send"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.single = TBSingleSend()
        self.group = TBGroupSend()
        self._username = ""

    def set_username(self, username: str):
        """注入当前用户（供 excuse 询问时使用）"""
        self._username = username or ""
        self.single.set_username(self._username)
        self.group.set_username(self._username)

    def build_tools(self) -> List[Dict]:
        """父级唯一的 NapCat 模块入口 schema"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "通过 QQ 主动给好友或群发送消息、文件、链接。"
                    "内部会自动完成：选择目标、拟定消息内容、发送。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_type": {
                            "type": "string",
                            "enum": ["friend", "group"],
                            "description": "发送目标类型：friend 好友 / group 群聊",
                        },
                        "request": {
                            "type": "string",
                            "description": "发送需求描述，例如：给小王发一句生日快乐 / 在某个群发活动通知",
                        },
                    },
                    "required": ["target_type", "request"],
                },
            },
        }]

    def dispatch(self, name: str, arguments: Dict) -> str:
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        arguments = arguments or {}
        target_type = arguments.get("target_type", "friend")
        request = arguments.get("request", "")
        if target_type == "group":
            return self.group.execute(request, self._username)
        return self.single.execute(request, self._username)
