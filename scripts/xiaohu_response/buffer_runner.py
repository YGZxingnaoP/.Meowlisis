# -*- coding: utf-8 -*-
# scripts/xiaohu_response/buffer_runner.py
# 筱狐必回机器人：合并缓冲运行器
#
# 复刻主项目 func/toolbox/napcat/napcat_core/buffer.py 的「群聊缓冲」逻辑：
#   - 随机 5~15 秒等待，期间无新消息则 flush；
#   - 有新消息（同群同用户）合并 texts 并重置计时；
#   - 合并条数达到上限 10 条立即 flush；
#   - flush 文本用中文逗号「，」连接；无文本时用「{username}@了你」占位。
# 差异：flush 回调指向脚本自己的回复引擎（主项目 buffer 写死走主项目回复，故不可复用）。

import random
import threading


class XHBufferRunner:
    """按 (group_id, user_id) 聚合消息的合并缓冲，flush 时回调 on_flush(buf, text)"""

    # 与主项目 buffer.py 完全一致的参数
    BUFFER_WAIT_MIN = 5.0
    BUFFER_WAIT_MAX = 15.0
    BUFFER_MAX_ROUNDS = 10

    def __init__(self, log, on_flush):
        """
        :param log: 日志器
        :param on_flush: callable(buf: dict, text: str)，缓冲到期/满员时回调
        """
        self.log = log
        self.on_flush = on_flush
        self._lock = threading.Lock()
        # key=(group_id, user_id) -> {"group_id","group_name","user_id","username","self_id","texts","count","timer"}
        self._buffers = {}

    # ==================== 对外 ====================
    def add(self, parsed: dict):
        """一条目标消息进入缓冲：合并文本、重置随机计时；达到上限立即 flush。"""
        group_id = str(parsed.get("group_id", "") or "")
        user_id = str(parsed.get("user_id", "") or "")
        username = str(parsed.get("username", "") or "")
        self_id = str(parsed.get("self_id", "") or "")
        group_name = str(parsed.get("group_name", "") or "")
        text = str(parsed.get("text", "") or "").strip()

        key = (group_id, user_id)
        to_flush = None
        with self._lock:
            buf = self._buffers.get(key)
            if buf is None:
                buf = {
                    "group_id": group_id,
                    "group_name": group_name,
                    "user_id": user_id,
                    "username": username,
                    "self_id": self_id,
                    "texts": [],
                    "count": 0,
                    "timer": None,
                }
                self._buffers[key] = buf
            # 合并文本，更新身份
            if text:
                buf["texts"].append(text)
            buf["username"] = username or buf.get("username", "")
            buf["self_id"] = self_id or buf.get("self_id", "")
            buf["group_name"] = group_name or buf.get("group_name", "")
            # 取消旧定时器
            if buf["timer"] is not None:
                buf["timer"].cancel()
                buf["timer"] = None
            buf["count"] += 1
            # 达到上限：立即 flush
            if buf["count"] >= self.BUFFER_MAX_ROUNDS:
                to_flush = self._buffers.pop(key, None)
                self.log.info(f"[缓冲] 群 {group_id} 用户 {user_id} 达到上限 {self.BUFFER_MAX_ROUNDS} 次，立即回复")
            else:
                wait = random.uniform(self.BUFFER_WAIT_MIN, self.BUFFER_WAIT_MAX)
                timer = threading.Timer(wait, self._on_timeout, args=(key, buf["count"]))
                timer.daemon = True
                buf["timer"] = timer
                timer.start()
                self.log.info(
                    f"[缓冲] 群 {group_id} 用户 {user_id} 第 {buf['count']} 条消息，{wait:.1f} 秒后无新消息则回复"
                )
        if to_flush:
            self._flush(to_flush)

    def exists(self, group_id, user_id) -> bool:
        """该用户在该群是否已有等待中的缓冲（用于决定其它人普通消息是否并入）"""
        key = (str(group_id or ""), str(user_id or ""))
        with self._lock:
            return key in self._buffers

    def clear(self):
        """清空所有缓冲并取消定时器（停止时调用）"""
        with self._lock:
            for buf in self._buffers.values():
                if buf.get("timer") is not None:
                    buf["timer"].cancel()
            self._buffers.clear()
            self.log.info("[缓冲] 已清空全部缓冲")

    # ==================== 内部 ====================
    def _on_timeout(self, key: tuple, count: int):
        """定时器到期：若无新消息（count 未变）则取出并 flush"""
        to_flush = None
        with self._lock:
            buf = self._buffers.get(key)
            if buf is None or buf.get("count") != count:
                # 期间来了新消息，已重新计时，忽略本次超时
                return
            to_flush = self._buffers.pop(key, None)
        if to_flush:
            self.log.info(f"[缓冲] 群 {key[0]} 用户 {key[1]} 停顿超时，回复")
            self._flush(to_flush)

    def _flush(self, buf: dict):
        """合并 texts 为一条文本并回调回复引擎"""
        texts = [t for t in (buf.get("texts") or []) if t and t.strip()]
        if not texts:
            # 纯表情/纯@ 无文本：占位文本（与主项目 buffer 一致）
            text = f"{buf.get('username') or '有人'}@了你"
        else:
            text = "，".join(texts)
        try:
            self.on_flush(buf, text)
        except Exception:
            self.log.exception("缓冲 flush 回调异常")
