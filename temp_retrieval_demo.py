# -*- coding: utf-8 -*-
"""
临时脚本：演示知识库向量检索逻辑（仅示例，不执行）

用法：runtime\python.exe temp_retrieval_demo.py

说明：
    检索不是把整句话直接向量化，而是：
    1) 关键词判断（否定/搜索/知道）
    2) LLM 提取 keys（专有名词）
    3) keys 用空格拼接成 query 文本
    4) query 向量化
    5) ChromaDB 余弦检索 top_k 个 chunk
    6) chunk 原文截断 + 清洗 → 拼进提示词
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from func.database.config import CatLearnConfig
from func.database.database_core import CatLearnCore
from func.database.store.searching import CatLearnSearching
from func.database.store.build_prompt import CatLearnBuildPrompt
from func.database.store.port import get_embedding
from func.database.store.vector_db import CatLearnVectorDB


def demo(sentence: str):
    core = CatLearnCore()
    cfg = core.config

    print("=" * 64)
    print("输入句子:", sentence)

    # ---------- 第 1 步：关键词判断 ----------
    negated = core._is_negated(sentence)
    is_search = core._match_keywords(sentence, cfg.search_keywords)
    keyword_trigger = core._match_keywords(sentence, cfg.know_keywords)

    print(f"[1] 否定词命中={negated}  搜索词命中={is_search}  知道/了解命中={keyword_trigger}")

    if negated:
        print("     → 命中否定词，直接跳过检索")
        return
    if is_search:
        print("     → 命中搜索词，走网络搜索摘要，不走知识库检索")
        return

    # ---------- 第 2 步：LLM 提取 keys（不是用原句）----------
    keys = CatLearnSearching().extract_keys(sentence)
    print(f"[2] LLM 提取的 keys = {keys}")

    if not keys:
        print("     → 没有提取到针对性关键词，跳过检索")
        return

    # ---------- 第 3 步：keys 拼接成 query 文本 ----------
    query_text = " ".join(keys)
    print(f"[3] query 文本 = {query_text!r}   (注意：不是原句)")

    # ---------- 第 4 步：向量化 query ----------
    vec = get_embedding().embed_one(query_text)
    print(f"[4] query 向量维度 = {len(vec)}")

    # ---------- 第 5 步：余弦检索 ----------
    top_k = cfg.store_keyword_top_k if keyword_trigger else cfg.store_top_k
    results = CatLearnVectorDB().query(vec, top_k=top_k)
    print(f"[5] 检索 top_k={top_k}，命中 {len(results)} 条")
    for r in results[:3]:
        m = r.get("metadata") or {}
        print(f"     - dist={r.get('distance')} doc_name={m.get('doc_name')} site={m.get('site')}")

    # ---------- 第 6 步：截断 + 清洗 → 拼提示词 ----------
    snippet_len = 100 if keyword_trigger else 50
    print(f"[6] 最终插入提示词的内容（截断 {snippet_len} 字）：")
    markdown = CatLearnBuildPrompt().build(keys, top_k=top_k, keyword_trigger=keyword_trigger)
    print(markdown or "（无结果）")
    print()


if __name__ == "__main__":
    demo("你知道我的清楚恋爱物语果然有问题吗")
    demo("异环这款游戏真好玩，我想玩")
