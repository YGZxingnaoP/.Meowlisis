# -*- coding: utf-8 -*-
# func/database/store/dedup.py
# 检索结果审查：搜索词精确匹配已存文档 → 与已存原文做文本相似度比对，重复则舍弃

import re
from difflib import SequenceMatcher

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.store.vector_db import CatLearnVectorDB

# 相似度阈值（硬编码）：相似度 > 该值判定为重复，舍弃不入库
SIMILARITY_THRESHOLD = 0.6
# 比对的文本长度上限（避免超长网页正文导致 difflib 性能退化）
MAX_COMPARE_CHARS = 10000


def _normalize(text: str) -> str:
    """归一化：统一换行、压缩空白，去掉首尾空白"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _trim(text: str) -> str:
    """超长文本截断到 MAX_COMPARE_CHARS，避免 difflib 性能退化"""
    if len(text) <= MAX_COMPARE_CHARS:
        return text
    return text[:MAX_COMPARE_CHARS]


@singleton
class CatLearnDedup:
    """检索结果审查（单例）

    - 用 search_keys 精确匹配 doc_name，找到已存文档的全部 chunk；
    - 把 chunk 原文按顺序拼接成「旧文档原文」；
    - 与本次搜索爬取到的「新文档原文」做文本相似度比对（difflib）；
    - 相似度 > SIMILARITY_THRESHOLD 判定重复。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.vdb = CatLearnVectorDB()

    def is_duplicate(self, search_keys: str, new_text: str) -> bool:
        """判定新文本是否与已存同名词文档重复

        返回 True 表示重复（调用方应舍弃，不写库、不更新向量）。
        """
        key = str(search_keys or "").strip()
        if not key:
            return False
        chunks = self.vdb.get_by_doc_name(key)
        if not chunks:
            return False

        old_parts = [str(c.get("text", "") or "") for c in chunks]
        old_text = _trim(_normalize("\n".join(old_parts)))
        new_text = _trim(_normalize(new_text))
        if not old_text or not new_text:
            return False

        ratio = SequenceMatcher(None, old_text, new_text).ratio()
        self.log.info(f"[审查] doc_name={key} 旧/新文本相似度={ratio:.4f}")
        return ratio > SIMILARITY_THRESHOLD
