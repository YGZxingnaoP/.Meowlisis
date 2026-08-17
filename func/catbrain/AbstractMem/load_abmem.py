# -*- coding: utf-8 -*-
# func/catbrain/AbstractMem/load_abmem.py
# 记忆摘要加载与提示词构建：按 topics>tags>joint>importance 优先级检索

import os
import json
from typing import List, Dict

from func.log.default_log import DefaultLog
from func.catbrain.catbrain import MeowCatBrainConfig
from func.toolbox.txt_reader.jieba_segment import MeowJiebaSegmentTool


class MeowLoadAbstractMemory:
    """摘要记忆读取类：读取 meow.json 并按优先级检索构建 markdown 提示词"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowCatBrainConfig()
        self.jieba_tool = MeowJiebaSegmentTool()
        self.meow_path = os.path.join("character", "abstract_memory", "meow.json")

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
        """取最新一条摘要的 topic 作为当前话题（保证单 topic 检索）"""
        if not data:
            return ""
        return str(data[-1].get("topic", "") or "")

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
        """按优先级检索构建记忆摘要 markdown 提示词（limit 默认取配置）"""
        data = self.load()
        if not data:
            return ""
        limit = limit if limit is not None else self.config.summary_top_limit
        ranked = self._rank(data, current_message, username)
        lines = ["# 记忆摘要"]
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
