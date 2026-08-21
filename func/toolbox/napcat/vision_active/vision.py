# -*- coding: utf-8 -*-
# func/toolbox/napcat/vision_active/vision.py
# NapCat 主动视觉桥接：连接 meowvision，作为 napcat 链路的视觉统一入口
# 接收消息里的图片 / AI 主动触发的看图，都经由本模块转交 meowvision 完成理解

from typing import Dict, List, Optional

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.meowvision.vision_core import TBVisionCore


@singleton
class TBNapCatVisionActive:
    """NapCat 视觉桥接：连接 meowvision，统一 napcat 看图入口。

    - process()：看图 + 写记忆，返回 {description, reply}（私聊/群聊收到图片时调用）。
    - run()：主动看图，返回角色回复（AI 主动触发视觉时调用）。
    - build_tools()/dispatch()：主动视觉工具（napcat_view），供 napcat LLM toolcalls 触发。
    """

    TOOL_NAME = "napcat_view"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.vision = TBVisionCore()
        self._username = ""

    def set_username(self, username: str):
        """注入当前用户（供主动看图时使用）"""
        self._username = username or ""

    # ==================== 看图入口 ====================
    def process(self, images: List[str], user_message: str, username: str,
                need_description: bool = True, write_memory: bool = True,
                history_messages: Optional[List[dict]] = None) -> Dict[str, str]:
        """收到图片时看图：转交 meowvision，返回 {description, reply}（不发送、不清缓存）"""
        return self.vision.process(
            images, user_message, username,
            need_description=need_description, write_memory=write_memory,
            history_messages=history_messages,
        )

    def run(self, image_paths: List[str], user_message: str, username: str = "",
            need_description: bool = True) -> str:
        """主动看图：转交 meowvision，返回角色回复（meowvision 内部回传 TTS，napcat 侧不清缓存）"""
        return self.vision.run(
            image_paths or [], user_message, username or self._username,
            need_description=need_description,
        )

    # ==================== 主动视觉工具（供 napcat LLM toolcalls） ====================
    def build_tools(self) -> List[Dict]:
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "主动调用视觉模型看图片/看屏幕并回复。适用于：用户发来图片需要你判断内容、"
                    "或你想看看屏幕更好地陪伴用户时。可指定本地图片路径列表；不指定则使用缓存图片。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要查看的图片路径或 url 列表（可空）",
                        },
                        "user_message": {
                            "type": "string",
                            "description": "用户当前消息/看图指令（可空）",
                        },
                    },
                },
            },
        }]

    def dispatch(self, name: str, arguments: Dict) -> str:
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        arguments = arguments or {}
        image_paths = arguments.get("image_paths") or []
        user_message = arguments.get("user_message") or ""
        need_description = bool(image_paths)
        return self.run(image_paths, user_message, self._username, need_description)
