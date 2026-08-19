# -*- coding: utf-8 -*-
# func/toolbox/napcat/message/get_message.py
# 获取当前私聊消息：解析昵称、用户 ID、文本与动画表情

from typing import List, Optional


class TBGetMessage:
    """解析 OneBot v11 私聊消息事件，提取用户名、文本与动画表情"""

    @staticmethod
    def _parse_segments(segments) -> List[str]:
        """解析消息段列表，返回文本/表情 content 列表（按出现顺序）。

        - text 段：累加文本
        - 动画表情（mface，有 summary 名称）：单作一个文本 [动画表情：名称]
        - 无名称动画表情、静态 face、其他段：跳过
        """
        result: List[str] = []
        buf = ""
        for seg in segments or []:
            if not isinstance(seg, dict):
                continue
            stype = seg.get("type")
            data = seg.get("data") or {}
            if stype == "text":
                buf += str(data.get("text", "") or "")
            elif stype == "mface":
                # 先刷出已累积文本
                if buf.strip():
                    result.append(buf.strip())
                    buf = ""
                summary = str(data.get("summary", "") or "").strip()
                if summary:
                    result.append(f"[动画表情：{summary}]")
            # 其余类型（face/image/at 等）跳过
        if buf.strip():
            result.append(buf.strip())
        return result

    def parse(self, event: dict) -> Optional[dict]:
        """解析私聊消息事件，返回 {username, user_id, text, segments}"""
        if not isinstance(event, dict):
            return None
        sender = event.get("sender") or {}
        user_id = event.get("user_id") or sender.get("user_id")
        if user_id is None:
            return None
        username = str(sender.get("card") or sender.get("nickname") or user_id).strip() or str(user_id)
        contents = self._parse_segments(event.get("message"))
        text = "".join(contents)
        return {
            "username": username,
            "user_id": str(user_id),
            "text": text,
            "segments": contents,
        }
