# -*- coding: utf-8 -*-
# func/toolbox/danmaku/get_danmaku/get_danmaku.py
# 弹幕接收缓存模块（接口型工具，自发进行）
# - 普通弹幕：仅内存缓存队列（重启丢失），无上限，记录用户名与完整内容；
# - SC：单独列表，持久化到 .temp/bilive_sc.json（启动清空，回复后删除对应条目）。

import os
import json
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class TBDanmakuReceiver:
    """弹幕接收缓存：普通弹幕内存队列 + SC 持久化列表

    - 普通弹幕：仅内存，重启丢失；
    - SC：落盘 .temp/bilive_sc.json，每次回复后删除被回复的那条；
    - 启动时清空 SC 文件（不恢复历史 SC）。
    """

    SC_PATH = os.path.join(".temp", "bilive_sc.json")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.Lock()
        # 普通弹幕缓存队列：[{"username": ..., "content": ...}, ...]
        self.danmaku_list = []
        # SC 列表：[{"username": ..., "content": ..., "msg_id": ...}, ...]
        self.sc_list = []
        # 启动时清空 SC 文件
        self._clear_sc_file()

    # ==================== 普通弹幕 ====================
    def add_danmaku(self, username: str, content: str):
        """新增一条普通弹幕到内存队列"""
        content = (content or "").strip()
        if not content:
            return
        with self._lock:
            self.danmaku_list.append({"username": username or "用户", "content": content})

    def snapshot_danmaku(self) -> list:
        """获取当前普通弹幕队列快照（不消费）"""
        with self._lock:
            return list(self.danmaku_list)

    def clear_danmaku(self):
        """清空普通弹幕队列（每次回复后调用）"""
        with self._lock:
            self.danmaku_list = []

    # ==================== SC ====================
    def add_sc(self, username: str, content: str, msg_id: str = ""):
        """新增一条 SC 并落盘"""
        content = (content or "").strip()
        if not content:
            return
        item = {"username": username or "用户", "content": content, "msg_id": str(msg_id or "")}
        with self._lock:
            self.sc_list.append(item)
            self._write_sc_locked()

    def snapshot_sc(self) -> list:
        """获取当前 SC 列表快照"""
        with self._lock:
            return list(self.sc_list)

    def remove_sc(self, item: dict):
        """删除指定 SC（回复后调用），并落盘"""
        with self._lock:
            if item in self.sc_list:
                self.sc_list.remove(item)
                self._write_sc_locked()

    def pop_sc(self) -> dict:
        """取出队首 SC（供消费），不删除；返回 None 表示无 SC"""
        with self._lock:
            return self.sc_list[0] if self.sc_list else None

    # ==================== 落盘 ====================
    def _write_sc_locked(self):
        """将 sc_list 写入 .temp/bilive_sc.json（调用方需持有锁）"""
        try:
            os.makedirs(os.path.dirname(self.SC_PATH), exist_ok=True)
            with open(self.SC_PATH, "w", encoding="utf-8") as f:
                json.dump(self.sc_list, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入 SC 缓存文件失败")

    def _clear_sc_file(self):
        """启动时清空 SC 文件（不恢复历史 SC）"""
        try:
            os.makedirs(os.path.dirname(self.SC_PATH), exist_ok=True)
            with open(self.SC_PATH, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("清空 SC 缓存文件失败")
