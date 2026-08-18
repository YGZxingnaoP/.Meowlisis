# -*- coding: utf-8 -*-
# func/pipeline/short_memory.py
# 短期记忆桥接：统一收发 .temp/public_short_mem.json
#
# 使用说明（供后续模块接入）：
#   json 结构：[{"role": "user"/"assistant", "content": "...", "type": "llm_fast_response"}, ...]
#   - role/content 为可直接发送给 LLM API 的消息格式
#   - type 为程序内部识别标签，仅用于按来源独立裁剪，不会进入任何 API
#   - 一轮 = 一条 user + 一条 assistant（成对计数）
#   - 每个 type 独立上限（轮数），相同 type 超过上限时删除最旧一轮
#
# 接入方法：
#   1. 保存：ShortMemory().save({"role": "user", "content": "...", "type": "模块类型"}, max_rounds)
#   2. 加载：ShortMemory().load() -> [{"role": "...", "content": "..."}]（已去掉 type）

import os
import json
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class ShortMemory:
    """短期记忆桥接：负责 .temp/public_short_mem.json 的读取、保存与按 type 裁剪"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.path = os.path.join(".temp", "public_short_mem.json")
        self._lock = threading.Lock()

    def _read(self) -> list:
        """读取 json 全部记录（缺失或损坏时返回空列表）"""
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            self.log.exception("读取短期记忆失败")
            return []

    def _write(self, data: list):
        """写入 json（自动创建 .temp 目录）"""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入短期记忆失败")

    def save(self, message: dict, max_rounds: int):
        """保存一条短期记忆，并按该 type 的独立上限裁剪最旧一轮"""
        with self._lock:
            data = self._read()
            data.append(message)
            data = self._trim_by_type(data, message.get("type"), max_rounds)
            self._write(data)

    def _trim_by_type(self, data: list, mem_type, max_rounds: int) -> list:
        """按指定 type 裁剪：超过 max_rounds 轮时删除最旧的完整一轮"""
        if not mem_type or max_rounds <= 0:
            return data
        # 该 type 在数组中的索引（顺序追加，天然有序）
        type_indices = [i for i, m in enumerate(data) if m.get("type") == mem_type]
        # 计算该 type 的完整轮数（user + assistant 成对）
        rounds = 0
        i = 0
        while i + 1 < len(type_indices):
            idx1, idx2 = type_indices[i], type_indices[i + 1]
            if data[idx1].get("role") == "user" and data[idx2].get("role") == "assistant":
                rounds += 1
                i += 2
            else:
                break
        # 删除最旧的多余轮次（每轮2条）
        remove_count = max(0, rounds - max_rounds)
        if remove_count > 0:
            remove_indices = type_indices[: remove_count * 2]
            for idx in sorted(remove_indices, reverse=True):
                data.pop(idx)
        return data

    def load(self) -> list:
        """加载全部短期记忆（去掉 type 字段，返回可发送的 role/content 列表）"""
        result = []
        for m in self._read():
            if "role" in m and "content" in m:
                result.append({"role": m["role"], "content": m["content"]})
        return result
