# -*- coding: utf-8 -*-
# func/database/store/build_prompt.py
# 知识库检索并构建提示词：keys → bge 向量 → ChromaDB 检索 → markdown 块

import re

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.config.app_config import AppConfig
from func.database.config import CatLearnConfig
from func.database.store.port.bge import CatLearnEmbedding
from func.database.store.vector_db import CatLearnVectorDB


def _normalize(text: str) -> str:
    """压缩空白：把连续空白/换行压成单个空格或换行"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{2,}", "\n", text)
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.split("\n")]
    return "\n".join([l for l in lines if l])


def _smart_snippet(text: str, max_len: int, suffix: str = "…") -> str:
    """按句子边界智能截断，返回不超过约 max_len 的完整片段"""
    text = _normalize(text)
    if not text or max_len <= 0 or len(text) <= max_len:
        return text

    units = re.split(r"(?<=[。！？!?；;，,、\n])", text)
    units = [u for u in units if u and u.strip()]

    result = ""
    for unit in units:
        if not result and len(unit) > max_len:
            return unit[:max_len].rstrip() + suffix
        if len(result) + len(unit) > max_len:
            break
        result += unit
        if len(result) >= max_len:
            break

    result = result.rstrip("，,、。！？!?；; \t\n")
    if not result:
        return text[:max_len].rstrip() + suffix
    if len(result) < len(text):
        return result + suffix
    return result


@singleton
class CatLearnBuildPrompt:
    """知识库提示词构建器（单例）

    - 输入检索 keys，输出 markdown 块，标题为 "{角色名}的知识库"；
    - 检索 top_k 条最相关内容，插入 system_prompt（用户档案下方）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CatLearnConfig()
        self.embedding = CatLearnEmbedding()
        self.vdb = CatLearnVectorDB()

    def build(self, keys: list, top_k: int = None, keyword_trigger: bool = False) -> str:
        """构建知识库提示词块，无结果返回空字符串

        - 直接写知识内容，不带来源前缀；
        - keyword_trigger=True（知道/了解命中）截断 100 字，否则截断 50 字。
        """
        keys = [k for k in (keys or []) if k and str(k).strip()]
        if not keys:
            return ""
        top = top_k or self.config.store_top_k
        snippet_len = 100 if keyword_trigger else 50

        query_text = " ".join(keys)
        vec = self.embedding.embed_one(query_text)
        if not vec:
            return ""
        results = self.vdb.query(vec, top_k=top)
        if not results:
            return ""

        ai_name = AppConfig().ai_name or "喵呜"
        lines = [f"# {ai_name}的知识库"]
        for r in results:
            text = str(r.get("text", "") or "").strip()
            if not text:
                continue
            snippet = _smart_snippet(text, snippet_len)
            snippet = self._clean_for_prompt(snippet)
            if not snippet:
                continue
            lines.append(f"- {snippet}")
        if len(lines) <= 1:
            return ""
        return "\n".join(lines)

    @staticmethod
    def _clean_for_prompt(text: str) -> str:
        """取出阶段清洗：去掉 markdown 表格管道符、换行，转成单行干净文本

        - 不清理入库原文，只清洗【取出后】用于提示词的内容；
        - '|' 转成逗号；
        - 换行转成空格（不要换行）；
        - 合并连续逗号、压缩连续空白。
        """
        if not text:
            return ""
        # markdown 表格管道符 -> 逗号
        text = text.replace("|", "，")
        # 换行 -> 空格
        text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        # 压缩连续空白
        text = re.sub(r"\s+", " ", text)
        # 合并连续逗号（含空格间隔的），如 "， ，" -> "，"
        text = re.sub(r"(?:[，,、]\s*)+", "，", text)
        # 去掉开头可能残留的逗号（表格首列）
        text = text.strip(" ，,、")
        return text
