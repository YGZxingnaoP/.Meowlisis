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
        self._meowid = ""

    def set_meowid(self, meowid: str):
        """注入当前用户（供 excuse 询问时使用）"""
        self._meowid = meowid or ""
        self.single.set_meowid(self._meowid)
        self.group.set_meowid(self._meowid)

    def build_tools(self) -> List[Dict]:
        """父级唯一的 NapCat 模块入口 schema（内容信息直传）"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "通过 QQ 主动给好友或群发送消息、文件、链接。"
                    "要发什么内容直接填入 content_type/text/url/file_path；"
                    "发给谁由系统按好友列表/群列表确定；"
                    "拿不准发给谁或发什么时，把 need_clarify 设为 true 并给出 clarify_question。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_type": {
                            "type": "string",
                            "enum": ["friend", "group"],
                            "description": "发送目标类型：friend 好友 / group 群聊",
                        },
                        "content_type": {
                            "type": "string",
                            "enum": ["text", "link", "file", "image"],
                            "description": "要发送的内容类型",
                        },
                        "text": {"type": "string", "description": "content_type=text 时的正文"},
                        "url": {"type": "string", "description": "content_type=link 时的链接"},
                        "file_path": {
                            "type": "string",
                            "description": "content_type=file/image 时的本地文件或图片路径",
                        },
                        "at_name": {
                            "type": "string",
                            "description": "群聊里要 @ 的成员昵称/群名片，可空",
                        },
                        "request": {
                            "type": "string",
                            "description": "发送需求描述（可选）：给小王发一句生日快乐 / 在某个群发活动通知",
                        },
                        "need_clarify": {
                            "type": "boolean",
                            "description": "目标或内容不确定时置 true，由系统向用户追问",
                        },
                        "clarify_question": {
                            "type": "string",
                            "description": "need_clarify=true 时要问用户的问题",
                        },
                    },
                    "required": ["target_type"],
                },
            },
        }]

    def dispatch(self, name: str, arguments: Dict) -> str:
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        arguments = arguments or {}
        target_type = arguments.get("target_type", "friend")
        request = str(arguments.get("request", "") or "")
        # 内容信息直传（content_type + text/url/file_path）；目标由子工具按列表确定
        content_type = str(arguments.get("content_type", "") or "")
        text = str(arguments.get("text", "") or "")
        url = str(arguments.get("url", "") or "")
        file_path = str(arguments.get("file_path", "") or "")
        at_name = str(arguments.get("at_name", "") or "")
        # 上层 AI 明确需要澄清 → 先向用户追问，补齐后再执行
        if bool(arguments.get("need_clarify")):
            from func.toolbox.excuse import TBExcuse
            question = str(arguments.get("clarify_question") or
                           "你想把这条消息发给谁？发什么内容呢？")
            clarify = TBExcuse().ask(question, meowid=self._meowid)
            if clarify:
                request = f"{request}；用户补充：{clarify}".strip("；")
        if target_type == "group":
            return self.group.execute(request, self._meowid, content_type=content_type,
                                      text=text, url=url, file_path=file_path, at_name=at_name)
        return self.single.execute(request, self._meowid, content_type=content_type,
                                   text=text, url=url, file_path=file_path)
