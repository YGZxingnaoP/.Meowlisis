# -*- coding: utf-8 -*-
# func/database/store/dedup.py
# 入库前重复过滤：逐 chunk 做精确指纹比对（不做模糊匹配）

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.store.vector_db import CatLearnVectorDB, doc_digest


@singleton
class CatLearnDedup:
    """入库前重复过滤（单例）

    判定方式：把待入库文本切成 chunk，逐个算文本 md5，与库内已有 chunk 的指纹
    集合比对。指纹相同即判定为重复，不做任何模糊相似度计算。

    为什么不再用 SequenceMatcher：
        旧实现把「该 doc_name 下全部 chunk 拼成一整篇」当旧文本，再和单篇新文本
        算相似度。分母随文档增长被稀释，ratio 单调下降 —— 同一个页面被反复抓取
        时越到后面越拦不住。实测：异环（237 chunk / 拼接 45271 字）与同一段 191
        字正文的 ratio 只有 0.0375，28 份完全相同的正文全部入库；而逐 chunk 比对
        的相似度是 1.0000，一次性拦住。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.vdb = CatLearnVectorDB()

    def filter_new_chunks(self, chunks: list):
        """过滤掉库内已存在的 chunk。

        Args:
            chunks: 待入库的文本块列表。

        Returns:
            tuple[list, int]: (需要入库的新 chunk 列表, 被判为重复的 chunk 数)。

        """
        items = [str(c) for c in (chunks or []) if c and str(c).strip()]
        if not items:
            return [], 0

        known = set(self.vdb.document_hashes())
        new_chunks = []
        dup = 0
        for c in items:
            dg = doc_digest(c)
            # 既跟库内已有指纹比，也跟本批次已接受的比：
            # 同一篇里重复出现的段落只应入库一次
            if dg in known:
                dup += 1
                continue
            known.add(dg)
            new_chunks.append(c)
        return new_chunks, dup

    def is_duplicate(self, chunks: list) -> bool:
        """整篇是否已完全存在（所有 chunk 都能在库内找到）。"""
        items = [str(c) for c in (chunks or []) if c and str(c).strip()]
        if not items:
            return False
        new_chunks, _dup = self.filter_new_chunks(items)
        return not new_chunks
