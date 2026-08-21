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
