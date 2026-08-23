# -*- coding: utf-8 -*-
# func/database/store/vector_db.py
# ChromaDB 本地向量库封装：初始化、写入、检索（供 learning / build_prompt 共用）

import os
import uuid

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.config import CatLearnConfig


@singleton
class CatLearnVectorDB:
    """ChromaDB 本地向量库（单例）

    - 持久化目录 .DataBase/chroma；
    - collection 名 knowledge，余弦相似度；
    - add：批量写入 chunk（documents + metadatas + embeddings）；
    - query：按向量检索 top_k，返回文档与元数据。
    """

    COLLECTION = "knowledge"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CatLearnConfig()
        self._client = None
        self._collection = None
        self._init()

    def _init(self):
        try:
            import chromadb
            db_dir = os.path.join(self.config.store_db_dir, "chroma")
            os.makedirs(db_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(path=db_dir)
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
            self.log.info(f"ChromaDB 知识库已就绪: {db_dir}")
        except Exception as e:
            self.log.error(f"ChromaDB 初始化失败: {e}")
            self._client = None
            self._collection = None

    @property
    def available(self) -> bool:
        return self._collection is not None

    def add_chunks(self, chunks: list) -> int:
        """批量写入 chunk。

        chunk 结构：{"text": str, "metadata": dict}
        返回写入条数。
        """
        if not self.available or not chunks:
            return 0
        ids = []
        docs = []
        metas = []
        for c in chunks:
            ids.append(uuid.uuid4().hex)
            docs.append(str(c.get("text", "")))
            m = c.get("metadata") or {}
            metas.append({k: str(v) for k, v in m.items()})
        try:
            self._collection.add(ids=ids, documents=docs, metadatas=metas)
            return len(ids)
        except Exception:
            self.log.exception("ChromaDB 写入失败")
            return 0

    def add_with_embeddings(self, chunks: list, embeddings: list) -> int:
        """批量写入带向量的 chunk（embedding 由外部 bge 计算）。

        chunk 结构：{"text": str, "metadata": dict}
        embeddings：与 chunks 一一对应的向量。
        """
        if not self.available or not chunks or not embeddings:
            return 0
        ids = []
        docs = []
        metas = []
        embeds = []
        for c, vec in zip(chunks, embeddings):
            if not vec:
                continue
            ids.append(uuid.uuid4().hex)
            docs.append(str(c.get("text", "")))
            m = c.get("metadata") or {}
            metas.append({k: str(v) for k, v in m.items()})
            embeds.append(list(vec))
        if not ids:
            return 0
        try:
            self._collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embeds)
            return len(ids)
        except Exception:
            self.log.exception("ChromaDB 带向量写入失败")
            return 0

    def upsert_with_embeddings(self, chunks: list, embeddings: list, ids: list = None) -> int:
        """幂等写入带向量的 chunk（用于预填充种子数据，避免重复）。

        chunk 结构：{"text": str, "metadata": dict}
        embeddings：与 chunks 一一对应的向量。
        ids：与 chunks 一一对应的主键；缺省自动生成（自动生成时非幂等）。
        """
        if not self.available or not chunks or not embeddings:
            return 0
        ids = list(ids or [])
        if len(ids) != len(chunks):
            ids = [uuid.uuid4().hex for _ in chunks]
        docs = []
        metas = []
        embeds = []
        used_ids = []
        for c, vec, cid in zip(chunks, embeddings, ids):
            if not vec:
                continue
            docs.append(str(c.get("text", "")))
            m = c.get("metadata") or {}
            metas.append({k: str(v) for k, v in m.items()})
            embeds.append(list(vec))
            used_ids.append(cid)
        if not docs:
            return 0
        try:
            self._collection.upsert(
                ids=used_ids,
                documents=docs,
                metadatas=metas,
                embeddings=embeds,
            )
            return len(docs)
        except Exception:
            self.log.exception("ChromaDB 幂等写入失败")
            return 0

    def has_source(self, source_type: str) -> bool:
        """判断知识库中是否已存在指定 source_type 的记录（用于种子幂等跳过）"""
        if not self.available:
            return False
        try:
            res = self._collection.get(
                where={"source_type": str(source_type)},
                limit=1,
            )
            return bool(res and res.get("ids"))
        except Exception:
            self.log.exception("ChromaDB 查询失败")
            return False

    def delete_source(self, source_type: str) -> int:
        """删除指定 source_type 的全部记录，返回删除条数（用于重新预填充前清理）"""
        if not self.available:
            return 0
        try:
            res = self._collection.get(
                where={"source_type": str(source_type)},
                include=[],
            )
            ids = (res or {}).get("ids") or []
            if ids:
                self._collection.delete(ids=ids)
            return len(ids)
        except Exception:
            self.log.exception("ChromaDB 删除失败")
            return 0

    def get_by_doc_name(self, doc_name: str) -> list:
        """按 doc_name 精确查询全部 chunk，返回 [{"text": str, "metadata": dict}]（按存储顺序）"""
        if not self.available or not doc_name:
            return []
        try:
            res = self._collection.get(
                where={"doc_name": str(doc_name)},
                include=["documents", "metadatas"],
            )
            docs = (res or {}).get("documents") or []
            metas = (res or {}).get("metadatas") or []
            out = []
            for i in range(len(docs)):
                out.append({
                    "text": docs[i] if i < len(docs) else "",
                    "metadata": metas[i] if i < len(metas) else {},
                })
            return out
        except Exception:
            self.log.exception("ChromaDB 按 doc_name 查询失败")
            return []

    def query(self, query_embeddings: list, top_k: int = 5) -> list:
        """按向量检索，返回 [{"text": str, "metadata": dict, "distance": float}]"""
        if not self.available or not query_embeddings:
            return []
        try:
            res = self._collection.query(
                query_embeddings=[list(query_embeddings)],
                n_results=int(top_k),
                include=["documents", "metadatas", "distances"],
            )
            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            out = []
            for i in range(len(docs)):
                out.append({
                    "text": docs[i] if i < len(docs) else "",
                    "metadata": metas[i] if i < len(metas) else {},
                    "distance": dists[i] if i < len(dists) else None,
                })
            return out
        except Exception:
            self.log.exception("ChromaDB 检索失败")
            return []
