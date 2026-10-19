# -*- coding: utf-8 -*-
# func/database/store/source_ingest.py
# 外部资料批量入库：接收已整理好的文本，统一走「留档 → 分块 → 精确去重 → 向量化 → 写库」
#
# 与 learning（网页搜索结果入库）的区别：
#   - 不抓取，调用方自己负责取数（语雀 API / 本地 json 等）；
#   - 留档目录按来源分桶（.DataBase/raw/ext_<source_type>/），与网页批次并列但互不混淆；
#   - 不走 is_junk 质量门（人工整理的短条目也有效，例如一句短评）；
#   - 去重、分块、向量化、metadata 结构与 learning 完全一致，检索侧无需区分。

import json
import os
import time

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.config import CatLearnConfig
from func.database.commet.chunker import CatLearnChunker
from func.database.store.dedup import CatLearnDedup
from func.database.store.port import get_embedding
from func.database.store.vector_db import CatLearnVectorDB


@singleton
class CatLearnSourceIngest:
    """外部资料入库器（单例）"""

    # 外部来源的留档批次前缀（与网页批次的 <时间戳>_<hex> 区分开）
    BATCH_PREFIX = "ext"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CatLearnConfig()
        self.chunker = CatLearnChunker()
        self.dedup = CatLearnDedup()
        self.embedding = get_embedding()
        self.vdb = CatLearnVectorDB()

    # ==================== 留档 ====================
    @property
    def raw_dir(self) -> str:
        return os.path.join(self.config.store_db_dir, "raw")

    @staticmethod
    def _safe_name(s: str) -> str:
        keep = []
        for ch in str(s or ""):
            keep.append(ch if (ch.isalnum() or ch in "-_.") else "_")
        out = "".join(keep).strip("_")
        return (out or "doc")[:64]

    def _archive(self, doc: dict, text: str) -> str:
        """把一篇正文与元数据留档到 .DataBase/raw/ext_<source_type>/<doc_key>/

        与网页归档同构（content.txt + meta.json），方便统一查看与离线重建。
        """
        try:
            st = self._safe_name(doc.get("source_type") or "unknown")
            batch = f"{self.BATCH_PREFIX}_{st}"
            key = self._safe_name(doc.get("source_id") or doc.get("doc_name") or "doc")
            d = os.path.join(self.raw_dir, batch, key)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "content.txt"), "w", encoding="utf-8") as f:
                f.write(text)
            meta = {
                "source_type": str(doc.get("source_type") or ""),
                "source_id": str(doc.get("source_id") or ""),
                "doc_name": str(doc.get("doc_name") or ""),
                "url": str(doc.get("url") or ""),
                "site": str(doc.get("site") or ""),
                "tags": str(doc.get("tags") or ""),
                "chars": len(text),
                "archived_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            return d
        except Exception:
            self.log.exception(f"留档失败: {doc.get('doc_name', '')}")
            return ""

    def _write_batch_meta(self, batch: str, source_type: str, n_docs: int):
        """写批次元数据（与网页批次同名文件，便于统一统计）"""
        try:
            d = os.path.join(self.raw_dir, batch)
            os.makedirs(d, exist_ok=True)
            meta = {
                "batch_id": batch,
                "kind": "external",
                "source_type": source_type,
                "doc_count": n_docs,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(os.path.join(d, "_batch_meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception(f"写批次元数据失败: {batch}")

    # ==================== 入库 ====================
    def ingest(self, docs: list, target_tokens: int = 256,
               overlap_ratio: float = 0.1, archive: bool = True) -> dict:
        """批量入库。

        Args:
            docs: 文档列表，每项形如
                {
                  "text": 正文（必填）,
                  "source_type": "yuque" / "watchlist" ...,
                  "source_id": 稳定文档键（建议 md5(唯一来源) 前缀化）,
                  "doc_name": 展示名,
                  "url": 来源链接（可空）,
                  "site": 站点/来源（可空）,
                  "tags": 标签串（可空）,
                }
            target_tokens: 分块目标 token 数。
            overlap_ratio: 分块重叠比例。

        Returns:
            dict: {"docs": 文档数, "empty": 空文档数, "dup_docs": 整篇重复数,
                   "chunks": 写入 chunk 数, "dup_chunks": 跳过 chunk 数}

        """
        stats = {"docs": 0, "empty": 0, "dup_docs": 0, "units": 0,
                 "chunks": 0, "dup_chunks": 0, "archived": 0}

        from func.database.store.text_clean import build_units

        items = [dict(d or {}) for d in (docs or [])]
        batch_counts = {}      # batch 名 -> 已留档篇数

        for doc in items:
            raw_text = str(doc.get("text") or "").strip()
            if not raw_text:
                stats["empty"] += 1
                continue

            # 先留档（存原始正文，保留可重放性）
            if archive:
                if self._archive(doc, raw_text):
                    stats["archived"] += 1
                    st = self._safe_name(doc.get("source_type") or "unknown")
                    batch = f"{self.BATCH_PREFIX}_{st}"
                    batch_counts[batch] = batch_counts.get(batch, 0) + 1

            # 按标题分段 + 小节内切块，每块自带《文档》·小节 前缀
            units = build_units(raw_text, str(doc.get("doc_name") or ""),
                                self.chunker, target_tokens=target_tokens,
                                overlap_ratio=overlap_ratio)
            if not units:
                stats["empty"] += 1
                continue
            stats["docs"] += 1
            stats["units"] += len(units)

            texts = [u["text"] for u in units]
            new_texts, dup = self.dedup.filter_new_chunks(texts)
            stats["dup_chunks"] += dup
            if not new_texts:
                stats["dup_docs"] += 1
                self.log.info(f"[入库] 整篇已存在，跳过: {doc.get('doc_name', '')}")
                continue

            by_text = {}
            for u in units:
                by_text.setdefault(u["text"], u)
            sel = [by_text[t] for t in new_texts]

            vectors = self.embedding.embed_texts(new_texts)
            if not vectors:
                self.log.error(f"[入库] 向量化失败，跳过: {doc.get('doc_name', '')}")
                continue

            payload = [{"text": u["text"], "metadata": self._meta(doc, u)} for u in sel]
            written = self.vdb.add_with_embeddings(payload, vectors)
            stats["chunks"] += written
            self.log.info(
                f"[入库] {doc.get('doc_name', '')}: {len(new_texts)} 块"
                f"（小节 {len(units)}，跳过重复 {dup} 块）"
            )

        # 补批次元数据（每来源一份，覆盖写）
        for batch, n in batch_counts.items():
            st = batch[len(self.BATCH_PREFIX) + 1:]
            self._write_batch_meta(batch, st, n)

        self.log.info(f"[入库] 完成: {stats}")
        return stats

    @staticmethod
    def _meta(doc: dict, unit: dict = None) -> dict:
        """统一 metadata 结构（与 learning 对齐，value 全部为 str）

        增加小节信息：section 保留标题原文（不做分类/映射），
        section_index / chunk_index / chunk_total 仅供参考与调试。
        """
        unit = unit or {}
        return {
            "source_type": str(doc.get("source_type") or ""),
            "source_id": str(doc.get("source_id") or ""),
            "doc_name": str(doc.get("doc_name") or ""),
            "url": str(doc.get("url") or ""),
            "site": str(doc.get("site") or ""),
            "tags": str(doc.get("tags") or ""),
            "section": str(unit.get("section") or ""),
            "section_index": str(unit.get("section_index") or 0),
            "chunk_index": str(unit.get("chunk_index") or 1),
            "chunk_total": str(unit.get("chunk_total") or 1),
        }
