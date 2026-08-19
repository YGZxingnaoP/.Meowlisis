# -*- coding: utf-8 -*-
# func/toolbox/napcat/message/get_record.py
# 获取当前用户聊天记录，整合为短期记忆（OpenAI messages 格式）

from typing import List

from func.log.default_log import DefaultLog
from func.toolbox.napcat.config import TBNapCatConfig
from func.toolbox.napcat.message.get_message import TBGetMessage


class TBGetRecord:
    """拉取私聊历史并合并为短期记忆（连续同角色消息合并，动画表情单独成条）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()

    def fetch(self, user_id: str, self_id: str, limit: int = None) -> List[dict]:
        """拉取历史消息并构建 OpenAI messages（旧→新，user/assistant）"""
        limit = limit if limit is not None else self.config.history_limit
        history = self._fetch_history(user_id, limit)
        if not history:
            return []
        # 按时间升序（旧在前）
        history = sorted(history, key=lambda m: int(m.get("time", 0) or 0))
        return self._build_messages(history, str(self_id))

    def _fetch_history(self, user_id: str, limit: int) -> List[dict]:
        """调用 NapCat API 拉取私聊历史"""
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            core = TBNapCatCore()
            ret = core.call_action_sync(
                "get_friend_msg_history",
                {"user_id": int(user_id), "count": int(limit)},
            )
            if not isinstance(ret, dict):
                return []
            messages = ret.get("messages") or ret.get("data") or []
            if isinstance(messages, dict):
                messages = messages.get("messages") or []
            return [m for m in messages if isinstance(m, dict)]
        except Exception:
            self.log.exception(f"拉取私聊历史失败: {user_id}")
            return []

    def _build_messages(self, history: List[dict], self_id: str) -> List[dict]:
        """合并连续同角色消息（逗号衔接），动画表情单独成条，换角色另起"""
        result: List[dict] = []
        self_id = str(self_id or "")
        for msg in history:
            # OneBot 历史消息的发送者在 sender.user_id，顶层可能没有 user_id
            sender = msg.get("sender") or {}
            sender_id = str(msg.get("user_id") or sender.get("user_id") or "")
            role = "assistant" if (sender_id and sender_id == self_id) else "user"
            contents = TBGetMessage._parse_segments(msg.get("message"))
            if not contents:
                continue
            for content in contents:
                is_emote = content.startswith("[动画表情：")
                if result and result[-1]["role"] == role and not is_emote:
                    # 连续同角色普通文本：逗号衔接合并
                    result[-1]["content"] += "，" + content
                else:
                    # 换角色或动画表情：另起新 content
                    result.append({"role": role, "content": content})
        return result
