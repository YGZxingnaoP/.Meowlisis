# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/get_group_record.py
# 获取群聊历史记录，分用户整理为短期记忆（content 标注【用户名】:内容，跳过表情/转发）

import time
from typing import List

from func.log.default_log import DefaultLog
from func.toolbox.napcat.config import TBNapCatConfig
from func.toolbox.napcat.groupchat.get_group_message import TBGetGroupMessage
from func.toolbox.napcat.message.time_split import (
    GAP_SECONDS, build_markers, tier_of,
)


class TBGetGroupRecord:
    """拉取群聊历史并构建短期记忆（连续同用户消息合并，content 标注用户名）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()
        self.get_message = TBGetGroupMessage()

    def fetch(self, group_id: str, self_id: str, limit: int = None) -> List[dict]:
        """拉取群聊历史并构建 OpenAI messages（旧→新，user/assistant）"""
        limit = limit if limit is not None else self.config.group_history_limit
        history = self._fetch_history(group_id, limit)
        if not history:
            return []
        history = sorted(history, key=lambda m: int(m.get("time", 0) or 0))
        return self._build_messages(history, str(self_id))

    def fetch_raw(self, group_id: str, limit: int = None) -> List[dict]:
        """拉取群聊原始历史（供群性质概括采样使用），时间升序"""
        limit = limit if limit is not None else self.config.group_history_limit
        history = self._fetch_history(group_id, limit)
        if not history:
            return []
        return sorted(history, key=lambda m: int(m.get("time", 0) or 0))

    def _fetch_history(self, group_id: str, limit: int) -> List[dict]:
        """调用 NapCat API 拉取群聊历史"""
        try:
            from func.toolbox.napcat.napcat_core import TBNapCatCore
            ret = TBNapCatCore().call_action_sync(
                "get_group_msg_history",
                {"group_id": int(group_id), "count": int(limit)},
            )
            if not isinstance(ret, dict):
                return []
            messages = ret.get("messages") or ret.get("data") or []
            if isinstance(messages, dict):
                messages = messages.get("messages") or []
            return [m for m in messages if isinstance(m, dict)]
        except Exception:
            self.log.exception(f"拉取群聊历史失败: {group_id}")
            return []

    def _build_messages(self, history: List[dict], self_id: str) -> List[dict]:
        """合并连续同用户消息，间隔 6 小时以上断开并插入会话分割标记"""
        result: List[dict] = []
        self_id = str(self_id or "")
        now = int(time.time())
        prev_ts = 0
        for msg in history:
            ts = int(msg.get("time", 0) or 0) or prev_ts or now
            prev_ts = ts
            sender = msg.get("sender") or {}
            sender_id = str(msg.get("user_id") or sender.get("user_id") or "")
            role = "assistant" if (sender_id and sender_id == self_id) else "user"
            username = str(sender.get("card") or sender.get("nickname") or sender_id or "未知").strip()
            segments = self.get_message._parse_segments(msg.get("message"))
            if not segments:
                continue
            tier = tier_of(ts, now)
            last = result[-1] if result else None
            time_break = bool(last) and (
                tier != last.get("_tier") or ts - last.get("_ts", 0) >= GAP_SECONDS)
            if (last and last["role"] == role and last.get("_user") == sender_id
                    and not time_break):
                # 连续同用户：追加到上一条
                last["content"] += "，" + "，".join(segments)
                last["_ts"] = ts
            else:
                # 换用户或跨 6 小时：另起一条
                result.append({"role": role,
                               "content": f"【{username}】:" + "，".join(segments),
                               "_user": sender_id, "_tier": tier, "_ts": ts})
        return build_markers(result)
