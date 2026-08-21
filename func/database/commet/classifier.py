# -*- coding: utf-8 -*-
# func/database/commet/classifier.py
# AI 自动分类打标签（移植自 Comet app/core/rag/classifier.py）

import json

from func.log.default_log import DefaultLog
from func.database.search.port import get_search_llm


class CatLearnClassifier:
    """内容分类打标签：宽泛主题大类，最多 2 个，优先复用已有标签"""

    PROMPT = (
        "你是内容分类助手。阅读下面文本，打 1 到 2 个宽泛中文主题标签。\n"
        "【已有标签】（优先复用，语义吻合就直接用，不要造近义词）：\n{existing}\n\n"
        "规则：\n"
        "- 优先从已有标签选择；都不合适才创造 1 个新的宽泛标签；\n"
        "- 标签必须是宽泛主题大类（技术、学习、工作、财经、生活、健康、读书笔记），不是具体关键词；\n"
        "- 每个标签 2~6 个字，最多 2 个；\n"
        "- 只输出 JSON 数组，形如 [\"技术\",\"学习\"]，不要额外文字。\n\n"
        "文本内容：\n{content}"
    )

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def classify(self, content: str, existing_tags: list = None) -> list:
        """生成分类标签，失败返回空列表（不阻断主流程）"""
        snippet = (content or "")[:1500]
        if not snippet.strip():
            return []
        existing = "、".join(existing_tags) if existing_tags else "（暂无，可自行创造）"
        llm = get_search_llm()
        if llm is None or not llm.client:
            return []
        try:
            resp = llm.chat(
                [{"role": "user", "content": self.PROMPT.format(existing=existing, content=snippet)}],
                temperature=0.2,
            )
            return self._parse(resp)
        except Exception as e:
            self.log.warning(f"AI 分类失败（忽略）: {e}")
            return []

    @staticmethod
    def _parse(resp) -> list:
        if not resp or not getattr(resp, "choices", None):
            return []
        try:
            answer = (resp.choices[0].message.content or "").strip()
        except Exception:
            return []
        text = answer
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            return []
        try:
            arr = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return []
        result = []
        for t in arr:
            if isinstance(t, str) and t.strip():
                result.append(t.strip()[:16])
        return result[:2]
