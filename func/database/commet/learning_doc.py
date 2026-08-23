# -*- coding: utf-8 -*-
# func/database/commet/learning_doc.py
# 文档入库入口：解析文档 → 分块 → bge-m3 向量化 → 写入知识库

import os
import json

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.commet.parser import CatLearnParser
from func.database.commet.chunker import CatLearnChunker
from func.database.commet.classifier import CatLearnClassifier
from func.database.store.port import get_embedding
from func.database.store.vector_db import CatLearnVectorDB


@singleton
class CatLearnDocLearning:
    """文档入库（单例）

    - 扫描项目根目录 .DataBase/inbox 下的文档文件；
    - parser 解析 → chunker 分块 → classifier 打标 → bge-m3 向量化 → 入库；
    - 处理完的文件移到 .DataBase/raw_docs/。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.parser = CatLearnParser()
        self.chunker = CatLearnChunker()
        self.classifier = CatLearnClassifier()
        self.embedding = get_embedding()
        self.vdb = CatLearnVectorDB()

    @property
    def inbox_dir(self) -> str:
        return os.path.join(".DataBase", "inbox")

    @property
    def done_dir(self) -> str:
        return os.path.join(".DataBase", "raw_docs")

    def scan_and_learn(self) -> int:
        """扫描 inbox 全部文档入库，返回入库 chunk 数"""
        if not os.path.isdir(self.inbox_dir):
            return 0
        total = 0
        for name in os.listdir(self.inbox_dir):
            path = os.path.join(self.inbox_dir, name)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in CatLearnParser.SUPPORTED_EXTS:
                continue
            try:
                with open(path, "rb") as f:
                    content = f.read()
                text = self.parser.parse_document(ext, content)
                if text.strip():
                    total += self._learn_text(text, name)
            except Exception:
                self.log.exception(f"文档入库失败: {name}")
                continue
            self._archive(path, name)
        return total

    def _learn_text(self, text: str, doc_name: str) -> int:
        """对解析出的文本分块、打标、向量化、入库"""
        chunks = self.chunker.chunk(text, target_tokens=256, overlap_ratio=0.1)
        chunks = [c for c in chunks if c and c.strip()]
        if not chunks:
            return 0
        tags = self.classifier.classify(text[:3000])
        vectors = self.embedding.embed_texts(chunks)
        payload = [{
            "text": c,
            "metadata": {
                "source_type": "document",
                "source_id": doc_name,
                "doc_name": doc_name,
                "tags": json.dumps(tags, ensure_ascii=False),
            },
        } for c in chunks]
        return self.vdb.add_with_embeddings(payload, vectors)

    def _archive(self, path: str, name: str):
        try:
            os.makedirs(self.done_dir, exist_ok=True)
            dest = os.path.join(self.done_dir, name)
            if os.path.exists(dest):
                os.remove(dest)
            os.rename(path, dest)
        except Exception:
            self.log.exception(f"文档归档失败: {name}")
