# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/get_group_message.py
# 获取当前群聊消息：解析群名、用户名、文本、@ 列表，跳过所有表情/转发/聊天记录等

import re
from typing import List, Optional

from func.log.default_log import DefaultLog
from func.toolbox.napcat.config import TBNapCatConfig


class TBGetGroupMessage:
    """解析 OneBot v11 群聊消息事件，提取文本与 @ 信息（跳过表情/转发/聊天记录等）"""

    # 需要跳过的消息段类型（表情、图片、转发合并聊天记录、语音视频、卡片等）
    SKIP_TYPES = {
        "face", "mface", "image", "record", "video", "forward",
        "json", "xml", "reply", "music", "share", "contact", "location",
        "redbag", "poke", "gift", "markdown", "keyboard", "node",
    }

    # markdown mention 链接：mqqapi://markdown/mention?at_type=1&at_tinyid=QQ号
    MENTION_RE = re.compile(r"mqqapi://markdown/mention\?[^)\s]*at_tinyid=(\d+)")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()

    @staticmethod
    def _parse_segments(segments) -> List[str]:
        """解析群消息段：仅保留 text 段，其余（表情/图片/转发等）全部跳过。

        返回按顺序的纯文本内容列表（与私聊不同，这里不保留任何动画表情）。
        """
        result: List[str] = []
        buf = ""
        for seg in segments or []:
            if not isinstance(seg, dict):
                continue
            stype = seg.get("type")
            if stype == "text":
                buf += str((seg.get("data") or {}).get("text", "") or "")
            elif stype == "at":
                # @ 单独记录在 at_list 中，不进入正文
                continue
            # 其余类型全部跳过（face/mface/image/forward/record 等）
        if buf.strip():
            result.append(buf.strip())
        return result

    @staticmethod
    def _markdown_to_text(content: str) -> str:
        """markdown 段 content 转纯文本（去掉加粗/链接/图片/内联命令）"""
        text = content or ""
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = text.replace("**", "")
        return text.strip()

    @staticmethod
    def _parse_markdown(segments) -> str:
        """提取 markdown 段纯文本（无 text 段时兜底）"""
        texts = []
        for seg in segments or []:
            if isinstance(seg, dict) and seg.get("type") == "markdown":
                t = TBGetGroupMessage._markdown_to_text(
                    str((seg.get("data") or {}).get("content", "") or "")
                )
                if t:
                    texts.append(t)
        return "\n".join(texts)

    @staticmethod
    def _parse_at_list(segments) -> List[str]:
        """提取消息中被 @ 的 QQ 号列表（去重保持顺序）"""
        result: List[str] = []
        for seg in segments or []:
            if not isinstance(seg, dict):
                continue
            if seg.get("type") == "at":
                qq = str((seg.get("data") or {}).get("qq", "") or "").strip()
                if qq and qq not in result:
                    result.append(qq)
        return result

    @staticmethod
    def _markdown_mention_targets(segments) -> List[str]:
        """从 markdown 段提取 mention 的 at_tinyid（被 @ 的 QQ 号列表，去重保持顺序）"""
        result: List[str] = []
        for seg in segments or []:
            if not isinstance(seg, dict):
                continue
            if seg.get("type") == "markdown":
                content = str((seg.get("data") or {}).get("content", "") or "")
                for qq in TBGetGroupMessage.MENTION_RE.findall(content):
                    if qq and qq not in result:
                        result.append(qq)
        return result

    def in_blacklist(self, group_name: str) -> bool:
        """判断群名是否命中黑名单（默认空，不拦截）"""
        blacklist = self.config.group_blacklist
        if not blacklist:
            return False
        name = str(group_name or "").strip()
        return name in [str(b).strip() for b in blacklist]

    def parse(self, event: dict) -> Optional[dict]:
        """解析群聊消息事件。

        返回 {
            group_id, group_name, username, user_id, self_id,
            text, segments, at_list, at_self, is_self, raw_message
        }
        """
        if not isinstance(event, dict):
            return None
        group_id = event.get("group_id")
        if group_id is None:
            return None
        sender = event.get("sender") or {}
        user_id = event.get("user_id") or sender.get("user_id")
        if user_id is None:
            return None
        self_id = event.get("self_id")

        username = str(sender.get("card") or sender.get("nickname") or user_id).strip() or str(user_id)
        raw_message = event.get("message") or []
        segments = self._parse_segments(raw_message)
        at_list = self._parse_at_list(raw_message)
        text = "".join(segments)
        # markdown 兜底：无 text 段时用 markdown 纯文本
        if not text.strip():
            text = self._parse_markdown(raw_message)

        at_self = False
        if str(self_id or "") and str(self_id) in at_list:
            at_self = True

        return {
            "group_id": str(group_id),
            "group_name": "",
            "username": username,
            "user_id": str(user_id),
            "self_id": str(self_id or ""),
            "text": text,
            "segments": segments,
            "at_list": at_list,
            "at_self": at_self,
            "is_self": str(user_id) == str(self_id or ""),
            "mention_self": str(self_id or "") in self._markdown_mention_targets(raw_message),
            "raw_message": raw_message,
        }
