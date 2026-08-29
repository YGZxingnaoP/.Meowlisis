# -*- coding: utf-8 -*-
# func/toolbox/napcat/napcat_core/buffer.py
# NapCat 消息聚合缓冲：私聊缓冲 + 群聊 @ 缓冲

import random
import threading


class TBNapCatBuffer:
    """消息聚合缓冲：随机等待区间内合并连发消息，达到上限或超时后交给上层 AI。

    - 私聊缓冲按 user_id 聚合；
    - 群聊 @ 缓冲按 (group_id, user_id) 聚合，仅检测该用户后续消息。
    本类不依赖连接层，只依赖配置与 get_record（发缓冲前拉历史）。
    """

    # 消息聚合缓冲：随机等待区间（秒）与连续等待循环上限
    BUFFER_WAIT_MIN = 5.0
    BUFFER_WAIT_MAX = 15.0
    BUFFER_MAX_ROUNDS = 10

    def __init__(self, log, config, get_record):
        self.log = log
        self.config = config
        self.get_record = get_record

        # 私聊消息聚合缓冲：user_id -> {"username","user_id","self_id","texts","count","timer"}
        self._buffer_lock = threading.Lock()
        self._buffers = {}

        # 群聊 @ 消息聚合缓冲：(group_id, user_id) -> {"group_id","user_id","username","self_id","group_name","texts","count","timer"}
        self._group_buffer_lock = threading.Lock()
        self._group_buffers = {}

    # ==================== 私聊缓冲 ====================
    def _buffer_message(self, parsed: dict, self_id):
        """将用户消息放入缓冲：无新消息则随机 5~15 秒后发送，有新消息则合并重新计时，上限 10 次"""
        user_id = parsed["user_id"]
        to_flush = None
        with self._buffer_lock:
            buf = self._buffers.get(user_id)
            if buf is None:
                buf = {
                    "username": parsed["username"],
                    "user_id": user_id,
                    "self_id": self_id,
                    "texts": [],
                    "count": 0,
                    "timer": None,
                }
                self._buffers[user_id] = buf
            # 合并文本，更新身份
            buf["texts"].append(parsed["text"])
            buf["username"] = parsed["username"]
            buf["self_id"] = self_id
            # 取消旧定时器
            if buf["timer"] is not None:
                buf["timer"].cancel()
                buf["timer"] = None
            buf["count"] += 1
            # 达到循环上限：立即发送，不再等待
            if buf["count"] >= self.BUFFER_MAX_ROUNDS:
                to_flush = self._buffers.pop(user_id, None)
                self.log.info(f"[NapCat缓冲] 用户 {user_id} 达到上限 {self.BUFFER_MAX_ROUNDS} 次，立即发送")
            else:
                wait = random.uniform(self.BUFFER_WAIT_MIN, self.BUFFER_WAIT_MAX)
                timer = threading.Timer(wait, self._on_buffer_timeout, args=(user_id, buf["count"]))
                timer.daemon = True
                buf["timer"] = timer
                timer.start()
                self.log.info(
                    f"[NapCat缓冲] 用户 {user_id} 第 {buf['count']} 条消息，{wait:.1f} 秒后无新消息则发送"
                )
        if to_flush:
            self._send_buffered(to_flush)

    def _on_buffer_timeout(self, user_id: str, count: int):
        """缓冲定时器到期：若无新消息（count 未变），取出并发送"""
        to_flush = None
        with self._buffer_lock:
            buf = self._buffers.get(user_id)
            if buf is None or buf["count"] != count:
                # 期间来了新消息，已重新计时，忽略本次超时
                return
            to_flush = self._buffers.pop(user_id, None)
        if to_flush:
            self.log.info(f"[NapCat缓冲] 用户 {user_id} 停顿超时，发送合并消息（共 {len(to_flush['texts'])} 条）")
            self._send_buffered(to_flush)

    def _send_buffered(self, buf: dict):
        """将缓冲中的合并消息发送给 AI（重新拉取最新历史作为短期记忆）"""
        username = buf["username"]
        user_id = buf["user_id"]
        self_id = buf["self_id"]
        text = "，".join(t for t in buf["texts"] if t and t.strip())
        if not text.strip():
            return
        try:
            short_memory = self.get_record.fetch(user_id, self_id)
            from func.toolbox.toolbox_core import TBoxCore
            TBoxCore().receive_qq(username, user_id, text, short_memory)
        except Exception:
            self.log.exception("发送缓冲消息异常")

    def _take_pending_text(self, user_id: str) -> str:
        """取出并取消某用户尚未发送的聚合文本缓冲（图片到达时合并到视觉输入）。

        返回合并后的纯文本；无缓冲则返回空串。调用后该用户缓冲被清空、定时器取消。
        """
        with self._buffer_lock:
            buf = self._buffers.pop(str(user_id or ""), None)
            if buf is None:
                return ""
            timer = buf.get("timer")
            if timer is not None:
                timer.cancel()
            texts = [t for t in (buf.get("texts") or []) if t and t.strip()]
        return "，".join(texts)

    def _clear_buffers(self):
        """清空所有缓冲并取消定时器（停止时调用）"""
        with self._buffer_lock:
            for buf in self._buffers.values():
                if buf.get("timer") is not None:
                    buf["timer"].cancel()
            self._buffers.clear()

    # ==================== 群聊 @ 聚合缓冲 ====================
    @staticmethod
    def _group_buffer_key(group_id, user_id) -> tuple:
        return (str(group_id or ""), str(user_id or ""))

    def group_buffer_exists(self, group_id, user_id) -> bool:
        """该用户在群聊中是否有等待中的 @ 缓冲"""
        with self._group_buffer_lock:
            return self._group_buffer_key(group_id, user_id) in self._group_buffers

    def buffer_group_at(self, parsed: dict) -> dict:
        """@ 消息进入群聊缓冲。若该用户已有缓冲（新的 @），先取出旧缓冲并取消计时。

        返回被挤出的旧缓冲（无则返回 None），由调用方决定是否立即 flush 旧的回复任务。
        """
        group_id = str(parsed.get("group_id", "") or "")
        user_id = str(parsed.get("user_id", "") or "")
        username = str(parsed.get("username", "") or "")
        self_id = str(parsed.get("self_id", "") or "")
        group_name = str(parsed.get("group_name", "") or "")
        text = str(parsed.get("text", "") or "").strip()

        key = self._group_buffer_key(group_id, user_id)
        old = None
        with self._group_buffer_lock:
            # 新的 @：挤出旧缓冲
            if key in self._group_buffers:
                old = self._group_buffers.pop(key)
                if old.get("timer") is not None:
                    old["timer"].cancel()

            buf = {
                "group_id": group_id,
                "user_id": user_id,
                "username": username,
                "self_id": self_id,
                "group_name": group_name,
                "texts": [text] if text else [],
                "count": 0,
                "timer": None,
            }
            self._group_buffers[key] = buf
            buf["count"] = 1
            wait = random.uniform(self.BUFFER_WAIT_MIN, self.BUFFER_WAIT_MAX)
            timer = threading.Timer(wait, self._on_group_buffer_timeout,
                                    args=(group_id, user_id, buf["count"]))
            timer.daemon = True
            buf["timer"] = timer
            timer.start()
            self.log.info(f"[NapCat群缓冲] 群 {group_id} 用户 {user_id} @ 触发，{wait:.1f} 秒后无新消息则回复")

        return old

    def add_group_buffer_text(self, parsed: dict):
        """合并该用户后续文本/表情到群聊缓冲，重置计时（仅检测该用户）"""
        group_id = str(parsed.get("group_id", "") or "")
        user_id = str(parsed.get("user_id", "") or "")
        text = str(parsed.get("text", "") or "").strip()
        if not text:
            return

        key = self._group_buffer_key(group_id, user_id)
        to_flush = None
        with self._group_buffer_lock:
            buf = self._group_buffers.get(key)
            if buf is None:
                return
            buf["texts"].append(text)
            buf["username"] = str(parsed.get("username", "") or buf.get("username", ""))
            if buf.get("timer") is not None:
                buf["timer"].cancel()
                buf["timer"] = None
            buf["count"] += 1
            if buf["count"] >= self.BUFFER_MAX_ROUNDS:
                to_flush = self._group_buffers.pop(key, None)
                self.log.info(f"[NapCat群缓冲] 群 {group_id} 用户 {user_id} 达到上限，立即回复")
            else:
                wait = random.uniform(self.BUFFER_WAIT_MIN, self.BUFFER_WAIT_MAX)
                timer = threading.Timer(wait, self._on_group_buffer_timeout,
                                        args=(group_id, user_id, buf["count"]))
                timer.daemon = True
                buf["timer"] = timer
                timer.start()
        if to_flush:
            self._flush_group_buffer(to_flush)

    def take_group_buffer(self, group_id, user_id) -> dict:
        """取出并取消该用户的群聊 @ 缓冲（图片/表情触发时），返回缓冲或 None"""
        key = self._group_buffer_key(group_id, user_id)
        with self._group_buffer_lock:
            buf = self._group_buffers.pop(key, None)
            if buf is not None and buf.get("timer") is not None:
                buf["timer"].cancel()
            return buf

    def _on_group_buffer_timeout(self, group_id: str, user_id: str, count: int):
        """群聊缓冲定时器到期：若无新消息（count 未变），取出并回复"""
        key = self._group_buffer_key(group_id, user_id)
        to_flush = None
        with self._group_buffer_lock:
            buf = self._group_buffers.get(key)
            if buf is None or buf.get("count") != count:
                return
            to_flush = self._group_buffers.pop(key, None)
        if to_flush:
            self.log.info(f"[NapCat群缓冲] 群 {group_id} 用户 {user_id} 停顿超时，回复")
            self._flush_group_buffer(to_flush)

    def _flush_group_buffer(self, buf: dict):
        """flush 群聊 @ 缓冲：纯 @ 无文本时用占位，交给 toolbox_core 走群聊文本回复"""
        texts = [t for t in (buf.get("texts") or []) if t and t.strip()]
        if not texts:
            text = f"{buf.get('username', '有人')}@了你"
        else:
            text = "，".join(texts)
        try:
            from func.toolbox.toolbox_core import TBoxCore
            TBoxCore().reply_group_at(buf, text)
        except Exception:
            self.log.exception("群聊 @ 缓冲 flush 异常")

    def _clear_group_buffers(self):
        """清空所有群聊 @ 缓冲并取消定时器（停止时调用）"""
        with self._group_buffer_lock:
            for buf in self._group_buffers.values():
                if buf.get("timer") is not None:
                    buf["timer"].cancel()
            self._group_buffers.clear()
