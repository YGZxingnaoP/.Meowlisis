# -*- coding: utf-8 -*-
# func/llm_active/origin/vision/get_response.py
# 主动回复视觉响应层：组装提示词 → 调用视觉模型 → 解析 {content, topic, tags}

import re
from typing import List, Dict, Optional

from func.log.default_log import DefaultLog
from func.llm_active.origin.vision.sender import AutoVisionSender


class AutoVisionGetResponse:
    """组装视频截图视觉提示词并解析视觉模型输出。

    输出三字段：
      - content：视频内容概括（≤300字，必要时逐帧描述）
      - topic：从话题枚举中选 1 个（TOPICS）
      - tags：从已有 tags 中选择，最多 3 个
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.sender = AutoVisionSender()

    def analyze(self, images: List[str], meta: Dict,
                topics: Optional[List[str]] = None,
                tags_pool: Optional[List[str]] = None) -> Dict[str, object]:
        """返回 {"content": str, "topic": str, "tags": list}"""
        topics = topics or []
        tags_pool = tags_pool or []

        system_prompt = (
            "你是一个视频内容理解助手。你会看到来自 B站某个视频的若干张截图，"
            "请结合视频元信息，准确理解并概括这个视频的内容。"
        )
        user_prompt = self._build_user_prompt(meta, topics, tags_pool)

        raw = self.sender.send(images, user_prompt, system_prompt)
        return self._split(raw, topics, tags_pool)

    @staticmethod
    def _build_user_prompt(meta: Dict, topics: List[str], tags_pool: List[str]) -> str:
        title = str(meta.get("title", "") or "").strip()
        uploader = str(meta.get("uploader", "") or "").strip()
        length = str(meta.get("len", "") or "").strip()
        label = str(meta.get("label", "") or "").strip()
        introduction = str(meta.get("introduction", "") or "").strip()

        lines = []
        if title:
            lines.append(f"视频标题：{title}")
        if label:
            lines.append(f"视频标签：{label}")
        if uploader:
            lines.append(f"UP主：{uploader}")
        if length:
            lines.append(f"视频时长：{length}")
        if introduction:
            lines.append(f"视频简介：{introduction}")

        topic_text = "、".join(topics) if topics else "日常"
        tags_text = "、".join(tags_pool) if tags_pool else "（暂无已有tags，可概括1~2个精炼短语）"

        lines.append("")
        lines.append(
            "这是你在b站上看到的视频，图片是几张截图。请描述一下你看到的内容，"
            "结合视频标题，描述一下视频内容。请尽量保证概括准确，"
            "仅在必要时（如画面有人物，或者场景极其美观复杂）逐帧描述，总字数控制在300字以内。"
        )
        lines.append("")
        lines.append("请严格按以下格式输出，不要输出其它内容：")
        lines.append("【内容】视频内容概括")
        lines.append(f"【话题】从[{topic_text}]中选择一个")
        lines.append(f"【tags】从已有tags中选择，最多3个，用顿号分隔：{tags_text}")

        return "\n".join(lines)

    @classmethod
    def _split(cls, raw, topics: List[str], tags_pool: List[str]) -> Dict[str, object]:
        if not raw:
            return {"content": "", "topic": "日常", "tags": []}
        text = str(raw)
        # 剥离 think 标签
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)

        content = cls._extract_section(text, "内容")
        topic = cls._extract_section(text, "话题").strip()
        tags_raw = cls._extract_section(text, "tags")

        topic = cls._norm_topic(topic, topics)
        tags = cls._norm_tags(tags_raw, tags_pool)

        return {"content": content, "topic": topic, "tags": tags}

    @staticmethod
    def _extract_section(text: str, marker: str) -> str:
        """按【marker】标记提取该段内容，缺失返回空串"""
        m = re.search(rf"【\s*{re.escape(marker)}\s*】(.*?)(?=【|\Z)", text, re.DOTALL)
        if not m:
            return ""
        return re.sub(r"\s+", " ", m.group(1)).strip()

    @staticmethod
    def _norm_topic(topic: str, topics: List[str]) -> str:
        """话题归一化：命中枚举则返回，否则归为日常"""
        t = (topic or "").strip()
        if not topics:
            return "日常"
        for item in topics:
            if item and item in t:
                return item
        return "日常"

    @staticmethod
    def _norm_tags(tags_raw: str, tags_pool: List[str]) -> List[str]:
        """tags 归一化：切分 → 去空白 → 最多3个 → 优先保留已有 tags"""
        if not tags_raw:
            return []
        parts = re.split(r"[、,，;；/|\s]+", tags_raw)
        cleaned = [p.strip() for p in parts if p and p.strip() not in ("无", "暂无", "没有")]
        # 去重保序
        seen = set()
        result = []
        for t in cleaned:
            if t not in seen:
                seen.add(t)
                result.append(t)
            if len(result) >= 3:
                break
        return result
