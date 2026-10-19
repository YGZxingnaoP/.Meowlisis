# -*- coding: utf-8 -*-
# func/toolbox/napcat/message/get_record.py
# 获取当前用户聊天记录，整合为短期记忆（OpenAI messages 格式）

import time
from typing import List

from func.log.default_log import DefaultLog
from func.toolbox.napcat.config import TBNapCatConfig
from func.toolbox.napcat.message.get_message import TBGetMessage
from func.toolbox.napcat.message.time_split import (
    GAP_SECONDS, build_markers, tier_of,
)


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
        """合并连续同角色消息，间隔 6 小时以上断开并插入会话分割标记"""
        result: List[dict] = []
        self_id = str(self_id or "")
        now = int(time.time())
        prev_ts = 0
        for msg in history:
            ts = int(msg.get("time", 0) or 0) or prev_ts or now
            prev_ts = ts
            # OneBot 历史消息的发送者在 sender.user_id，顶层可能没有 user_id
            sender = msg.get("sender") or {}
            sender_id = str(msg.get("user_id") or sender.get("user_id") or "")
            role = "assistant" if (sender_id and sender_id == self_id) else "user"
            contents = TBGetMessage._parse_segments(msg.get("message"))
            if not contents:
                continue
            tier = tier_of(ts, now)
            for content in contents:
                is_emote = content.startswith("[动画表情：")
                last = result[-1] if result else None
                time_break = bool(last) and (
                    tier != last.get("_tier") or ts - last.get("_ts", 0) >= GAP_SECONDS)
                if (last and last["role"] == role and not is_emote and not time_break):
                    # 连续同角色普通文本：逗号衔接合并
                    last["content"] += "，" + content
                    last["_ts"] = ts
                else:
                    # 换角色、动画表情或跨 6 小时：另起新 content
                    result.append({"role": role, "content": content,
                                   "_tier": tier, "_ts": ts})
        return build_markers(result)
