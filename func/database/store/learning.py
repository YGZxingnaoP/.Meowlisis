# -*- coding: utf-8 -*-
# func/database/store/learning.py
# 搜索学习入库：search 完成信号后，把 .temp/database/web_result 的网页文本向量化入库

import os
import json
import shutil
from threading import Thread

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.config import CatLearnConfig
from func.database.commet.chunker import CatLearnChunker
from func.database.store.port.bge import CatLearnEmbedding
from func.database.store.vector_db import CatLearnVectorDB


@singleton
class CatLearnLearning:
    """搜索结果入库（单例）

    - search 模块完成搜索后调用 on_search_done(batch_id)；
    - 访问 .temp/database/web_result/{batch_id}，逐 task 读取文本；
    - 分块 → bge-m3 向量化 → 写入 ChromaDB；
    - 处理完的原始文件移到 .DataBase/raw/{batch_id}（处理一个移一个，避免中断重复处理）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CatLearnConfig()
        self.chunker = CatLearnChunker()
        self.embedding = CatLearnEmbedding()
        self.vdb = CatLearnVectorDB()

    @property
    def web_result_dir(self) -> str:
        return os.path.join(".temp", "database", "web_result")

    @property
    def raw_dir(self) -> str:
        return os.path.join(self.config.store_db_dir, "raw")

    def on_search_done(self, batch_id: str):
        """search 完成信号入口：异步处理指定批次（不阻塞搜索链路）"""
        if not batch_id:
            return
        Thread(target=self._process_safe, args=(batch_id,), daemon=True).start()

    def _process_safe(self, batch_id: str):
        try:
            self.process_batch(batch_id)
        except Exception:
            self.log.exception(f"learning 处理批次 {batch_id} 异常")

    def process_batch(self, batch_id: str) -> int:
        """同步处理一个批次，返回入库 chunk 数"""
        batch_dir = os.path.join(self.web_result_dir, batch_id)
        if not os.path.isdir(batch_dir):
            self.log.warning(f"web_result 批次不存在: {batch_id}")
            return 0

        meta = self._read_json(os.path.join(batch_dir, "meta.json"))
        total = 0
        # 遍历 task 子文件夹
        for name in sorted(os.listdir(batch_dir)):
            task_dir = os.path.join(batch_dir, name)
            if not os.path.isdir(task_dir):
                continue
            try:
                total += self._process_task(batch_id, task_dir)
            except Exception:
                self.log.exception(f"learning 处理 task 失败: {task_dir}")
                continue

        # 移走批次 meta.json，清理空批次文件夹
        self._archive_meta(batch_dir, batch_id, meta)
        self.log.info(f"learning 批次 {batch_id} 完成，共入库 {total} 条")
        return total

    def _process_task(self, batch_id: str, task_dir: str) -> int:
        """处理单个 task：读文本 → 分块 → 向量化 → 入库 → 移出"""
        task_meta = self._read_json(os.path.join(task_dir, "meta.json"))
        content_path = os.path.join(task_dir, "content.txt")
        text = self._read_text(content_path)
        if not text.strip():
            self._archive_task(batch_id, task_dir)
            return 0

        chunks = self.chunker.chunk(text, target_tokens=256, overlap_ratio=0.1)
        chunks = [c for c in chunks if c and c.strip()]
        if not chunks:
            self._archive_task(batch_id, task_dir)
            return 0

        vectors = self.embedding.embed_texts(chunks)
        base_meta = {
            "source_type": "web",
            "source_id": str(task_meta.get("task_id", "")),
            "doc_name": str(task_meta.get("title", "") or task_meta.get("url", "")),
            "url": str(task_meta.get("url", "")),
            "site": str(task_meta.get("site", "")),
            "tags": str(task_meta.get("search_keys", "")),
        }
        payload = [{"text": c, "metadata": dict(base_meta)} for c in chunks]
        written = self.vdb.add_with_embeddings(payload, vectors)
        # 处理完移出（归档原始文件）
        self._archive_task(batch_id, task_dir)
        return written

    def _archive_task(self, batch_id: str, task_dir: str):
        """把 task 文件夹移到 .DataBase/raw/{batch_id}/"""
        try:
            dest_dir = os.path.join(self.raw_dir, str(batch_id))
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, os.path.basename(task_dir))
            if os.path.abspath(dest) != os.path.abspath(task_dir):
                if os.path.exists(dest):
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(task_dir, dest)
        except Exception:
            self.log.exception(f"归档 task 失败: {task_dir}")

    def _archive_meta(self, batch_dir: str, batch_id: str, meta: dict):
        """移走批次 meta.json 到 raw/{batch_id}/，随后删除空批次文件夹"""
        try:
            meta_path = os.path.join(batch_dir, "meta.json")
            if os.path.exists(meta_path):
                dest_dir = os.path.join(self.raw_dir, str(batch_id))
                os.makedirs(dest_dir, exist_ok=True)
                shutil.move(meta_path, os.path.join(dest_dir, "_batch_meta.json"))
            # 删除已空的批次文件夹
            if os.path.isdir(batch_dir) and not os.listdir(batch_dir):
                shutil.rmtree(batch_dir, ignore_errors=True)
        except Exception:
            self.log.exception(f"归档批次 meta 失败: {batch_dir}")

    @staticmethod
    def _read_json(path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _read_text(path: str) -> str:
        if not os.path.exists(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""
