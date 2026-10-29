# -*- coding: utf-8 -*-
# func/pipeline/short_memory.py
# 短期记忆桥接：统一收发 .temp/public_short_mem.json
#
# 使用说明（供后续模块接入）：
#   json 结构：[{"role": "user"/"assistant", "content": "...", "type": "..."}, ...]
#   - role/content 为可直接发送给 LLM API 的消息格式
#   - type 为程序内部识别标签，仅用于按来源独立裁剪，不会进入任何 API
#   - 一轮 = 一条 user + 一条 assistant（成对计数）
#   - 每个 type 独立上限（轮数），相同 type 超过上限时删除最旧一轮
#   - 插播类消息（llm_active_response / vision_response）不独立占轮，
#     而是挂靠到其后第一条 llm_fast_response，该条快回被淘汰时连带删除；
#     尾部孤立（其后无快回）的插播按兜底上限裁剪（llm_active_response 默认 50 条）
#
# 接入方法：
#   1. 保存：ShortMemory().save({"role": "user", "content": "...", "type": "模块类型"}, max_rounds)
#   2. 加载：ShortMemory().load() -> [{"role": "...", "content": "..."}]（已去掉 type）

import os
import json
import time
import bisect
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class ShortMemory:
    """短期记忆桥接：负责 .temp/public_short_mem.json 的读取、保存与裁剪"""

    # 插播类消息：挂靠到其后第一条 llm_fast_response，随该条快回淘汰而连带删除
    ACTIVE_TYPES = ("llm_active_response", "vision_response", "hum_song", "other_talks",
                    "toolbox_excuse")

    # 插播类各自的尾部兜底上限（未列出的取主动回复插播配置 _active_mem_limit）
    ACTIVE_LIMITS = {"toolbox_excuse": 8}

    SESSION_MARKER = "session_marker"

    MARKER_KEEP = 5

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.path = os.path.join(".temp", "public_short_mem.json")
        self._lock = threading.Lock()
        self._mark_session()

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

    def _mark_session(self):
        """启动时在短期记忆最下面插一条会话分割提示（及以上内容属于更早的对话）"""
        with self._lock:
            data = self._read()
            if not data:
                return
            now = time.strftime("%Y-%m-%d %H:%M")
            text = f"【会话分割】以上内容发生在 {now} 之前；此后的属于本次会话"
            if data[-1].get("type") == self.SESSION_MARKER:
                data[-1]["role"] = "system"
                data[-1]["content"] = text
                self._write(data)
                return
            data.append({
                "role": "system",
                "content": text,
                "type": self.SESSION_MARKER,
            })
            self._write(self._cleanup_markers(data))

    def _cleanup_markers(self, data: list) -> list:
        """分割记录随其上内容连带清理：无内容支撑的丢弃、连续只留最后一条、最多保留 MARKER_KEEP 条"""
        out = []
        has_content = False
        for m in data:
            if m.get("type") == self.SESSION_MARKER:
                if not has_content:
                    continue
                if out and out[-1].get("type") == self.SESSION_MARKER:
                    out[-1] = m
                    continue
                out.append(m)
            else:
                has_content = True
                out.append(m)
        idx = [i for i, m in enumerate(out) if m.get("type") == self.SESSION_MARKER]
        if len(idx) > self.MARKER_KEEP:
            for i in reversed(idx[:-self.MARKER_KEEP]):
                out.pop(i)
        return out

    def save(self, message: dict, max_rounds: int, trim_mode: str = "rounds"):
        """保存一条短期记忆，并按该 type 的独立上限裁剪最旧内容。

        :param max_rounds: 上限（rounds 模式为轮数，items 模式为条数）
        :param trim_mode: "rounds" 按轮裁剪（user+assistant 成对），"items" 按条裁剪
        """
        with self._lock:
            data = self._read()
            data.append(message)
            data = self._trim_by_type(data, message.get("type"), max_rounds, trim_mode)
            data = self._trim_active_orphans(data)
            data = self._cleanup_markers(data)
            self._write(data)

    def _trim_by_type(self, data: list, mem_type, max_rounds: int, trim_mode: str = "rounds") -> list:
        """按指定 type 裁剪旧内容。

        - trim_mode="items"：按条数裁剪，超出 max_rounds 条就删最旧 N 条（弹幕用）；
        - trim_mode="rounds"：完整轮按轮裁剪，孤立的不成对消息按条兜底裁剪，
          避免「user 后缺 assistant」的孤立消息无限堆积。
        - 仅 llm_fast_response 在 rounds 裁剪淘汰时，连带删除挂靠到它的插播类消息。
        """
        if not mem_type or max_rounds <= 0:
            return data
        type_indices = [i for i, m in enumerate(data) if m.get("type") == mem_type]

        if trim_mode == "items":
            remove_n = max(0, len(type_indices) - max_rounds)
            if remove_n > 0:
                for idx in sorted(type_indices[:remove_n], reverse=True):
                    data.pop(idx)
            return data

        # ===== rounds 模式 =====
        paired_rounds = []
        orphans = []
        i = 0
        n = len(type_indices)
        while i < n:
            if i + 1 < n:
                idx1, idx2 = type_indices[i], type_indices[i + 1]
                if data[idx1].get("role") == "user" and data[idx2].get("role") == "assistant":
                    paired_rounds.append((idx1, idx2))
                    i += 2
                    continue
            orphans.append(type_indices[i])
            i += 1

        remove_rounds = max(0, len(paired_rounds) - max_rounds)
        remove_orphans = max(0, len(orphans) - max_rounds)

        remove_set = set()
        removed_fast_indices = set()
        for idx1, idx2 in paired_rounds[:remove_rounds]:
            remove_set.add(idx1)
            remove_set.add(idx2)
            removed_fast_indices.add(idx1)
            removed_fast_indices.add(idx2)
        for idx in orphans[:remove_orphans]:
            remove_set.add(idx)
            removed_fast_indices.add(idx)

        # 插播挂靠删除：仅 llm_fast_response 被淘汰时，连带删掉挂靠到它的插播
        if mem_type == "llm_fast_response" and removed_fast_indices:
            for active_idx, fast_idx in self._link_active_to_fast(data).items():
                if fast_idx in removed_fast_indices:
                    remove_set.add(active_idx)

        if remove_set:
            for idx in sorted(remove_set, reverse=True):
                data.pop(idx)
        return data

    def _link_active_to_fast(self, data: list) -> dict:
        """插播类消息 → 其后第一条 llm_fast_response 索引（按 JSON 数组顺序）"""
        fast_indices = [i for i, m in enumerate(data) if m.get("type") == "llm_fast_response"]
        if not fast_indices:
            return {}
        links = {}
        for i, m in enumerate(data):
            if m.get("type") in self.ACTIVE_TYPES:
                pos = bisect.bisect_right(fast_indices, i)
                if pos < len(fast_indices):
                    links[i] = fast_indices[pos]
        return links

    def _trim_active_orphans(self, data: list) -> list:
        """插播兜底：对 ACTIVE_TYPES 各类型保留最近 N 条，避免尾部孤立无限堆积

        - N 取该类型在 ACTIVE_LIMITS 里的专属上限，未列出则取主动回复插播配置；
        - 专属上限为 0 表示该类型不做兜底（只依赖挂靠淘汰）。
        """
        default_limit = self._active_mem_limit()
        for active_type in self.ACTIVE_TYPES:
            limit = self.ACTIVE_LIMITS.get(active_type)
            if limit is None:
                limit = default_limit
            if limit <= 0:
                continue
            indices = [i for i, m in enumerate(data) if m.get("type") == active_type]
            remove_n = max(0, len(indices) - limit)
            if remove_n > 0:
                for idx in sorted(indices[:remove_n], reverse=True):
                    data.pop(idx)
        return data

    def _active_mem_limit(self) -> int:
        """读取主动回复插播兜底上限（默认 50）"""
        try:
            from func.llm_active.config import AutoActiveConfig
            return int(AutoActiveConfig().active_mem_limit)
        except Exception:
            return 50

    def load(self) -> list:
        """加载全部短期记忆（去掉 type 字段，返回可发送的 role/content 列表）"""
        result = []
        for m in self._read():
            if "role" in m and "content" in m:
                result.append({"role": m["role"], "content": m["content"]})
        return result

    def load_by_type(self, mem_types) -> list:
        """按来源类型加载短期记忆（保留 type，只取 user/assistant 且内容非空）

        导演判官只看主链路对话，不能被 QQ / 弹幕的行污染，因此必须按 type 过滤。
        """
        types = tuple(mem_types) if isinstance(mem_types, (list, tuple, set)) else (mem_types,)
        result = []
        for m in self._read():
            if m.get("type") not in types:
                continue
            if m.get("role") not in ("user", "assistant"):
                continue
            content = str(m.get("content") or "")
            if not content.strip():
                continue
            result.append({"role": m["role"], "content": content, "type": m.get("type")})
        return result
