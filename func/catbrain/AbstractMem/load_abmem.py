# -*- coding: utf-8 -*-
# func/catbrain/AbstractMem/load_abmem.py
# 记忆摘要加载与提示词构建：按 topics>tags>joint>importance 优先级检索

import os
import json
import time
from typing import List, Dict

from func.log.default_log import DefaultLog
from func.config.app_config import AppConfig
from func.catbrain.catbrain import MeowCatBrainConfig
from func.catbrain.AbstractMem.summary_tool import MeowSummaryTool
from func.catbrain.txt_reader.jieba_segment import MeowJiebaSegmentTool
from func.pipeline.short_memory import ShortMemory


class MeowLoadAbstractMemory:
    """摘要记忆读取类：读取 meow.json 并按优先级检索构建 markdown 提示词"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.jieba_tool = MeowJiebaSegmentTool()
        self.summary_tool = MeowSummaryTool()
        self.short_memory = ShortMemory()
        self.meow_path = os.path.join("character", "abstract_memory", "meow.json")
        # 当前话题落盘路径（供主动回复模块读取）
        self.topic_path = os.path.join(".temp", "current_topic.json")
        self._saved_topic = None
        # 当前话题缓存（内存单例，重启后从最新摘要回退）
        self._topic_cache = ""
        self._topic_cache_time = 0.0
        self._llm = None

    def _ensure_llm(self):
        """懒加载摘要独立 LLM 客户端（话题决策复用）"""
        if self._llm is None:
            if self.config.abstract_llm_type == "aliyun":
                from func.catbrain.AbstractMem.port.aliyun import MeowAbstractAliyunLLM
                self._llm = MeowAbstractAliyunLLM()
            else:
                from func.catbrain.AbstractMem.port.deepseek import MeowAbstractDeepSeekLLM
                self._llm = MeowAbstractDeepSeekLLM()
        return self._llm

    def load(self) -> List[Dict]:
        """读取 meow.json 全部摘要记忆（缺失或损坏时返回空列表）"""
        if not os.path.exists(self.meow_path):
            return []
        try:
            with open(self.meow_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            self.log.exception("读取 meow.json 失败")
            return []

    def _current_topic(self, data: List[Dict]) -> str:
        """当前话题：优先用缓存，过期后用短期记忆决策，失败回退到最新摘要"""
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
        fallback = str(data[-1].get("topic", "") or "")
        self._save_topic(fallback)
        return fallback

    def _save_topic(self, topic: str):
        """话题更新后实时落盘到 .temp/current_topic.json"""
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
        """用短期记忆强制工具调用决策当前话题（失败返回空）"""
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
        resp = llm.chat(messages, tools=self.summary_tool.build_topic_tool(),
                        tool_choice=self.summary_tool.force_topic_tool_choice())
        if not resp or not resp.choices:
            return ""
        try:
            msg = resp.choices[0].message
            for tc in (msg.tool_calls or []):
                if tc.function.name == "decide_topic":
                    args = json.loads(tc.function.arguments)
                    topic = str(args.get("topic", "") or "").strip()
                    if topic in self.summary_tool.TOPICS:
                        return topic
        except Exception:
            self.log.exception("话题决策失败")
        return ""

    def _tags_similarity(self, item: Dict, msg_words: set) -> float:
        """计算该条摘要前3个 tags 与当前消息的 jieba 关键词相似度"""
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
        """计算 joint 相似度：当前用户名在该条参与角色中则为1，否则为0"""
        joint = item.get("joint") or []
        if not username:
            return 0.0
        return 1.0 if username in joint else 0.0

    def _rank(self, data: List[Dict], current_message: str, username: str) -> List[Dict]:
        """按 topics>tags(前3相似度)>joint(相似度)>importance 优先级排序"""
        current_topic = self._current_topic(data)
        msg_words = set(self.jieba_tool.segment(current_message)) if current_message else set()
        scored = []
        for item in data:
            topic_match = 1.0 if (current_topic and item.get("topic") == current_topic) else 0.0
            tags_sim = self._tags_similarity(item, msg_words)
            joint_sim = self._joint_similarity(item, username)
            importance = float(item.get("importance", 0) or 0)
            scored.append(((topic_match, tags_sim, joint_sim, importance), item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    def build_prompt(self, current_message: str = "", username: str = "", limit: int = None) -> str:
        """按优先级检索构建记忆摘要 markdown 提示词（标题为「ai_name的记忆」，limit 默认取配置）"""
        data = self.load()
        if not data:
            return ""
        limit = limit if limit is not None else self.config.summary_top_limit
        ranked = self._rank(data, current_message, username)
        lines = [f"# {AppConfig().ai_name}的记忆"]
        for item in ranked[:limit]:
            topic = item.get("topic", "")
            tags = "、".join(item.get("tags") or [])
            joint = "、".join(item.get("joint") or [])
            meta = f"话题:{topic}"
            if tags:
                meta += f" | 标签:{tags}"
            if joint:
                meta += f" | 参与:{joint}"
            lines.append(f"- [{meta}] {item.get('text', '')}")
        return self._ensure_markdown("\n".join(lines))

    @staticmethod
    def _ensure_markdown(text: str) -> str:
        """检查并确保输出为 markdown 语法（缺标题或列表符时微调补全）"""
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
