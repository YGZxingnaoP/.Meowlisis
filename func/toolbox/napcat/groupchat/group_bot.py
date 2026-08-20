# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/group_bot.py
# 解析群机器人消息：识别群机器人、单独 @、解耦图片与文本内容

from typing import List, Optional

from func.log.default_log import DefaultLog
from func.toolbox.napcat.config import TBNapCatConfig


class TBGroupBot:
    """群机器人消息解析器：识别群机器人账号，解耦 @ / 图片 / 文本"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()

    def is_bot(self, user_id) -> bool:
        """判断发送者是否为已配置的群机器人（group_bots 映射 name->qq）"""
        uid = str(user_id or "")
        for qq in (self.config.group_bots or {}).values():
            if str(qq) == uid:
                return True
        return False

    def bot_name(self, user_id) -> str:
        """按 QQ 号反查群机器人名（找不到返回空串）"""
        uid = str(user_id or "")
        for name, qq in (self.config.group_bots or {}).items():
            if str(qq) == uid:
                return str(name)
        return ""

    @staticmethod
    def _extract_images(segments) -> List[str]:
        """提取图片段（仅 image，不含表情/动画），返回 url 或 file 路径列表"""
        result: List[str] = []
        for seg in segments or []:
            if not isinstance(seg, dict) or seg.get("type") != "image":
                continue
            data = seg.get("data") or {}
            url = str(data.get("url", "") or "").strip()
            file = str(data.get("file", "") or "").strip()
            result.append(url or file)
        return [x for x in result if x]

    @staticmethod
    def _extract_at_list(segments) -> List[str]:
        """提取被 @ 的 QQ 号列表（去重）"""
        result: List[str] = []
        for seg in segments or []:
            if isinstance(seg, dict) and seg.get("type") == "at":
                qq = str((seg.get("data") or {}).get("qq", "") or "").strip()
                if qq and qq not in result:
                    result.append(qq)
        return result

    @staticmethod
    def _extract_text(segments) -> str:
        """提取纯文本（跳过表情/图片/at/转发等）"""
        buf = ""
        for seg in segments or []:
            if isinstance(seg, dict) and seg.get("type") == "text":
                buf += str((seg.get("data") or {}).get("text", "") or "")
        return buf.strip()

    def parse(self, event: dict) -> Optional[dict]:
        """解析群机器人消息事件。

        返回 {
            group_id, user_id, self_id, is_bot, bot_name,
            text, images, at_list, at_self
        }
        """
        if not isinstance(event, dict):
            return None
        sender = event.get("sender") or {}
        user_id = event.get("user_id") or sender.get("user_id")
        self_id = event.get("self_id")
        if user_id is None:
            return None
        segments = event.get("message") or []
        at_list = self._extract_at_list(segments)
        return {
            "group_id": str(event.get("group_id", "") or ""),
            "user_id": str(user_id),
            "self_id": str(self_id or ""),
            "is_bot": self.is_bot(user_id),
            "bot_name": self.bot_name(user_id),
            "text": self._extract_text(segments),
            "images": self._extract_images(segments),
            "at_list": at_list,
            "at_self": bool(self_id and str(self_id) in at_list),
        }
