# -*- coding: utf-8 -*-
# func/toolbox/napcat/groupchat/get_group_record.py
# 获取群聊历史记录，分用户整理为短期记忆（content 标注【用户名】:内容，跳过表情/转发）

from typing import List

from func.log.default_log import DefaultLog
from func.toolbox.napcat.config import TBNapCatConfig
from func.toolbox.napcat.groupchat.get_group_message import TBGetGroupMessage


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
        """合并连续同用户消息，content 为【用户名】:消息内容；换用户另起"""
        result: List[dict] = []
        self_id = str(self_id or "")
        for msg in history:
            sender = msg.get("sender") or {}
            sender_id = str(msg.get("user_id") or sender.get("user_id") or "")
            role = "assistant" if (sender_id and sender_id == self_id) else "user"
            username = str(sender.get("card") or sender.get("nickname") or sender_id or "未知").strip()
            segments = self.get_message._parse_segments(msg.get("message"))
            if not segments:
                continue
            content = f"【{username}】:" + "，".join(segments)
            if result and result[-1]["role"] == role and result[-1].get("_user") == sender_id:
                # 连续同用户：追加到上一条
                result[-1]["content"] += "，" + "，".join(segments)
            else:
                item = {"role": role, "content": content, "_user": sender_id}
                result.append(item)
        # 去掉内部标记字段
        for item in result:
            item.pop("_user", None)
        return result
