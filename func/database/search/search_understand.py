# -*- coding: utf-8 -*-
# func/database/search/search_understand.py
# 关键词触发的搜索结果：仅文本摘要（50~80字），一次性插入提示词，不进知识库

import os
import json
import shutil
import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.search.port import get_search_llm


@singleton
class CatLearnSearchUnderstand:
    """搜索摘要（单例）

    - 关键词"搜索"触发的搜索，结果不进知识库；
    - 对每个 task 的纯文本摘要 50~80 字；
    - 摘要按用户存入 .temp/search_result.json；
    - 该用户下次说话读取一次后即清除（一次性）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.result_path = os.path.join(".temp", "search_result.json")
        self._lock = threading.Lock()

    @property
    def web_result_dir(self) -> str:
        return os.path.join(".temp", "database", "web_result")

    # ==================== 摘要写入 ====================
    def summarize_batch(self, batch_id: str, username: str):
        """对批次内每个 task 文本摘要，写入 search_result.json，随后清理批次文件"""
        batch_dir = os.path.join(self.web_result_dir, batch_id)
        if not os.path.isdir(batch_dir):
            return

        summaries = []
        for name in sorted(os.listdir(batch_dir)):
            task_dir = os.path.join(batch_dir, name)
            if not os.path.isdir(task_dir):
                continue
            meta = self._read_json(os.path.join(task_dir, "meta.json"))
            text = self._read_text(os.path.join(task_dir, "content.txt"))
            if not text.strip():
                continue
            summary = self._summarize(text)
            if not summary:
                continue
            summaries.append({
                "task_id": meta.get("task_id"),
                "search_keys": str(meta.get("search_keys", "") or ""),
                "summary": summary,
            })

        if summaries:
            self._append(username, summaries)

        # 一次性：摘要完清理该批次文件夹（不进库）
        try:
            shutil.rmtree(batch_dir, ignore_errors=True)
        except Exception:
            self.log.exception(f"清理摘要批次失败: {batch_dir}")

    def _summarize(self, text: str) -> str:
        """LLM 摘要 50~80 字，失败返回空"""
        llm = get_search_llm()
        if llm is None or not llm.client:
            self.log.error("搜索模块 LLM 不可用，无法摘要")
            return ""
        snippet = text[:4000]
        messages = [
            {
                "role": "system",
                "content": "你是内容摘要助手。把下面的内容概括成50到80字的中文摘要，只输出摘要正文，不要多余说明。",
            },
            {"role": "user", "content": snippet},
        ]
        resp = llm.chat(messages, temperature=0.3)
        if not resp or not getattr(resp, "choices", None):
            return ""
        try:
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            return ""

    # ==================== search_result.json 读写 ====================
    def _read_result(self) -> dict:
        if not os.path.exists(self.result_path):
            return {}
        try:
            with open(self.result_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_result(self, data: dict):
        try:
            os.makedirs(os.path.dirname(self.result_path), exist_ok=True)
            with open(self.result_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入 search_result.json 失败")

    def _append(self, username: str, summaries: list):
        with self._lock:
            data = self._read_result()
            key = username or "匿名"
            existing = data.get(key) or []
            if not isinstance(existing, list):
                existing = []
            existing.extend(summaries)
            data[key] = existing
            self._write_result(data)

    # ==================== 读取（一次性） ====================
    def take_result(self, username: str) -> str:
        """读取该用户全部摘要并清除，返回 markdown 文本（无则空串）"""
        with self._lock:
            data = self._read_result()
            key = username or "匿名"
            items = data.pop(key, None)
            if items is not None:
                self._write_result(data)
        if not items:
            return ""
        lines = ["## 网络搜索的结果"]
        for it in items:
            if not isinstance(it, dict):
                continue
            keys = str(it.get("search_keys", "") or "").strip()
            summary = str(it.get("summary", "") or "").strip()
            if summary:
                head = f"- {keys}" if keys else "-"
                lines.append(f"{head}：{summary}")
        if len(lines) <= 1:
            return ""
        return "\n".join(lines)

    # ==================== 工具方法 ====================
    @staticmethod
    def _read_json(path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _read_text(path: str) -> str:
        if not os.path.exists(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""
