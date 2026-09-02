# -*- coding: utf-8 -*-
"""摘要记忆加载与提示词构建：按证据分>准确度>话题>标签>参与>重要度检索"""
import os
import re
import json
import time
import datetime
import threading
from typing import List, Dict

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.summary_tool import MeowSummaryTool
from func.catbrain.AbstractMem.evidence import MeowEvidence
from func.catbrain.AbstractMem.port import force_tool_call
from func.catbrain.txt_reader.jieba_segment import MeowJiebaSegmentTool
from func.pipeline.short_memory import ShortMemory


class MeowLoadAbstractMemory:
    """摘要记忆读取类：读取 meow-*.json 并检索构建 markdown 提示词"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.jieba_tool = MeowJiebaSegmentTool()
        self.summary_tool = MeowSummaryTool()
        self.evidence = MeowEvidence()
        self.short_memory = ShortMemory()
        self.meow_dir = os.path.join("character", "abstract_memory")
        self.topic_path = os.path.join(".temp", "current_topic.json")
        self._saved_topic = None
        self._topic_cache = ""
        self._topic_cache_time = 0.0
        self._llm = None
        self._lock = threading.Lock()

    def _ensure_llm(self):
        """懒加载摘要独立 LLM 客户端"""
        if self._llm is None:
            if self.config.abstract_llm_type == "gemini":
                from func.catbrain.AbstractMem.port.gemini import MeowAbstractGeminiLLM
                self._llm = MeowAbstractGeminiLLM()
            elif self.config.abstract_llm_type == "aliyun":
                from func.catbrain.AbstractMem.port.aliyun import MeowAbstractAliyunLLM
                self._llm = MeowAbstractAliyunLLM()
            else:
                from func.catbrain.AbstractMem.port.deepseek import MeowAbstractDeepSeekLLM
                self._llm = MeowAbstractDeepSeekLLM()
        return self._llm

    @staticmethod
    def _current_meow_path() -> str:
        """按当前月份生成摘要文件路径"""
        yymm = datetime.datetime.now().strftime("%y%m")
        return os.path.join("character", "abstract_memory", f"meow-{yymm}.json")

    def load(self) -> List[Dict]:
        """读取所有 meow-*.json 摘要记忆并按 id 去重"""
        result = []
        seen = set()
        if not os.path.isdir(self.meow_dir):
            return result
        try:
            for fname in sorted(os.listdir(self.meow_dir)):
                if not (fname.startswith("meow-") and fname.endswith(".json")):
                    continue
                path = os.path.join(self.meow_dir, fname)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            if not isinstance(item, dict):
                                result.append(item)
                                continue
                            item_id = item.get("id")
                            if item_id:
                                if item_id in seen:
                                    continue
                                seen.add(item_id)
                            result.append(item)
                except Exception:
                    self.log.exception(f"读取 {fname} 失败")
        except Exception:
            self.log.exception("读取摘要目录失败")
        return result

    @staticmethod
    def _month_of(item: Dict) -> str:
        """从条目的 time 字段提取月份 YYMM；缺失或格式异常时回退当前月份"""
        if isinstance(item, dict) and item.get("time"):
            m = re.match(r"^(\d{4})-(\d{2})", str(item["time"]))
            if m:
                return m.group(1)[2:] + m.group(2)
        return datetime.datetime.now().strftime("%y%m")

    def save(self, data: List[Dict]):
        """按条目 time 字段的月份分文件写回，避免跨月数据整体写入当月文件

        - 每个条目按自己的月份落入 meow-YYMM.json（time 缺失回退当前月，不丢数据）；
        - 同月内按 id 去重（保留首次出现的条目）。
        """
        os.makedirs(self.meow_dir, exist_ok=True)
        by_month: Dict[str, List[Dict]] = {}
        seen: set = set()
        for item in data:
            if not isinstance(item, dict):
                by_month.setdefault(datetime.datetime.now().strftime("%y%m"), []).append(item)
                continue
            item_id = item.get("id")
            if item_id:
                if item_id in seen:
                    continue
                seen.add(item_id)
            month = self._month_of(item)
            by_month.setdefault(month, []).append(item)
        with self._lock:
            for month, items in by_month.items():
                path = os.path.join(self.meow_dir, f"meow-{month}.json")
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(items, f, ensure_ascii=False, indent=2)
                except Exception:
                    self.log.exception(f"写入摘要文件失败: {path}")

    def _current_topic(self, data: List[Dict]) -> str:
        """当前话题：缓存优先，过期后决策，失败回退最新摘要"""
        now = time.time()
        if self._topic_cache and (now - self._topic_cache_time) < self.config.topic_update_interval:
            self._save_topic(self._topic_cache)
            return self._topic_cache
        topic = self._decide_topic()
        if topic:
            self._topic_cache = topic
            self._topic_cache_time = now
            self._save_topic(topic)
            return topic
        if not data:
            return ""
        topics = data[-1].get("topics") or []
        fallback = topics[0] if topics else ""
        self._save_topic(fallback)
        return fallback

    def _save_topic(self, topic: str):
        """话题更新后落盘到 .temp/current_topic.json"""
        if not topic or topic == self._saved_topic:
            return
        try:
            os.makedirs(os.path.dirname(self.topic_path), exist_ok=True)
            with open(self.topic_path, "w", encoding="utf-8") as f:
                json.dump({"topic": topic}, f, ensure_ascii=False)
            self._saved_topic = topic
        except Exception:
            self.log.exception("保存当前话题失败")

    def _decide_topic(self) -> str:
        """用短期记忆强制工具调用决策当前话题"""
        llm = self._ensure_llm()
        if llm is None or not llm.client:
            return ""
        records = self.short_memory.load()
        if not records:
            return ""
        lines = []
        for m in records[-20:]:
            role = "用户" if m.get("role") == "user" else "AI"
            lines.append(f"{role}：{m.get('content', '')}")
        content = "\n".join(lines)
        messages = [
            {"role": "system", "content": "根据以下最近对话内容，判断当前对话的话题。"},
            {"role": "user", "content": content},
        ]
        resp = force_tool_call(llm, messages, self.summary_tool.build_topic_tool(), "decide_topic")
        if not resp or not resp.choices:
            return ""
        msg = resp.choices[0].message
        for tc in (msg.tool_calls or []):
            if tc.function.name == "decide_topic":
                args = self.summary_tool.parse_arguments(tc.function.arguments)
                topic = str((args or {}).get("topic", "") or "").strip()
                if topic in self.summary_tool.TOPICS:
                    return topic
        return ""

    def _tags_similarity(self, item: Dict, msg_words: set) -> float:
        """计算摘要 tags 与当前消息 jieba 关键词相似度"""
        tags = item.get("tags") or []
        if not tags or not msg_words:
            return 0.0
        best = 0.0
        for tag in tags[:3]:
            tag_words = set(self.jieba_tool.segment(str(tag)))
            if not tag_words:
                continue
            overlap = len(tag_words & msg_words)
            score = overlap / len(tag_words)
            if score > best:
                best = score
        return best

    def _joint_similarity(self, item: Dict, username: str) -> float:
        """计算 joint 相似度"""
        joint = item.get("joint") or []
        if not username:
            return 0.0
        return 1.0 if username in joint else 0.0

    def _rank(self, data: List[Dict], current_message: str, username: str,
              topic_override: str = "") -> List[Dict]:
        """按证据分>准确度>话题>标签>参与>重要度排序并硬过滤负分"""
        current_topic = topic_override or self._current_topic(data)
        msg_words = set(self.jieba_tool.segment(current_message)) if current_message else set()
        now = datetime.datetime.now()
        scored = []
        for item in data:
            evidence = item.get("evidence")
            if not isinstance(evidence, dict):
                evidence = {}
            score = self.evidence.score(evidence, now)
            if score < 0:
                continue
            topics = item.get("topics") or []
            topic_match = 1.0 if (current_topic and current_topic in topics) else 0.0
            tags_sim = self._tags_similarity(item, msg_words)
            joint_sim = self._joint_similarity(item, username)
            accuracy = float(item.get("accuracy", 0) or 0)
            importance = float(item.get("importance", 0) or 0)
            scored.append(((score, accuracy, topic_match, tags_sim, joint_sim, importance), item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    def build_prompt(self, current_message: str = "", username: str = "", limit: int = None,
                     topic_override: str = "") -> str:
        """构建记忆摘要 markdown 提示词"""
        data = self.load()
        if not data:
            return ""
        limit = limit if limit is not None else self.config.summary_top_limit
        ranked = self._rank(data, current_message, username, topic_override)
        lines = [f"# {AppConfig().ai_name}的记忆"]
        for item in ranked[:limit]:
            topics = "、".join(item.get("topics") or [])
            tags = "、".join(item.get("tags") or [])
            joint = "、".join(item.get("joint") or [])
            meta = f"话题:{topics}"
            if tags:
                meta += f" | 标签:{tags}"
            if joint:
                meta += f" | 参与:{joint}"
            lines.append(f"- [{meta}] {item.get('event', '')}")
        return self._ensure_markdown("\n".join(lines))

    @staticmethod
    def _ensure_markdown(text: str) -> str:
        """确保输出为 markdown 语法"""
        if not text:
            return ""
        lines = text.split("\n")
        if not lines[0].startswith("#"):
            lines.insert(0, "# 记忆摘要")
        fixed = []
        for line in lines[1:]:
            if line.strip() and not line.startswith(("#", "-", "*", ">", "|")):
                line = "- " + line
            fixed.append(line)
        return "\n".join([lines[0]] + fixed)
