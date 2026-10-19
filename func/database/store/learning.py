# -*- coding: utf-8 -*-
# func/database/store/learning.py
# 搜索学习入库：search 完成信号后，把 .temp/database/web_result 的网页文本向量化入库

import hashlib
import os
import json
import shutil
from threading import Thread

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.config import CatLearnConfig
from func.database.commet.chunker import CatLearnChunker
from func.database.store.port import get_embedding
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
        self.embedding = get_embedding()
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
        """处理单个 task：读文本 → 审查去重 → 分块 → 向量化 → 入库 → 移出"""
        task_meta = self._read_json(os.path.join(task_dir, "meta.json"))
        content_path = os.path.join(task_dir, "content.txt")
        text = self._read_text(content_path)
        if not text.strip():
            self._delete_task(task_dir)
            return 0

        search_keys = str(task_meta.get("search_keys", "") or "").strip()

        # 内容质量门：反爬挑战页 / 错误页 / 过短内容一律不入库。
        # 采集层已拦一次，这里再拦一次覆盖其它写入路径与历史残留。
        try:
            from func.database.search.content_quality import is_junk
            junk, reason = is_junk(text)
            if junk:
                self.log.warning(
                    f"[审查] 内容质量不合格（{reason}），舍弃并删除: {search_keys}"
                )
                self._delete_task(task_dir)
                return 0
        except Exception:
            self.log.exception("内容质量检查异常，继续正常入库")

        results = task_meta.get("results") or []
        first = results[0] if results else {}
        # doc_name 统一为「搜索词」，同时作为分块前缀
        doc_name = search_keys or str(
            first.get("title", "")
            or task_meta.get("title", "")
            or task_meta.get("url", "")
            or ""
        ).strip()
        if not doc_name:
            doc_name = str(task_meta.get("task_id", ""))

        # 按标题分段 + 小节内切块（与 source_ingest 同一套实现）。
        # 每块自带《文档》·小节 前缀，标题原文保留为 metadata.section。
        from func.database.store.text_clean import build_units
        units = build_units(text, doc_name, self.chunker,
                            target_tokens=256, overlap_ratio=0.1)
        if not units:
            self._archive_task(batch_id, task_dir)
            return 0

        unit_texts = [u["text"] for u in units]
        # 审查：逐单元精确去重（指纹比对，不做模糊匹配）。
        # 先过滤再向量化，避免给库内已有的块白付 embedding 调用。
        try:
            from func.database.store.dedup import CatLearnDedup
            new_texts, dup_count = CatLearnDedup().filter_new_chunks(unit_texts)
            if dup_count:
                self.log.info(
                    f"[审查] {search_keys}: 跳过库内已存在的 {dup_count} 块，"
                    f"新增 {len(new_texts)} 块"
                )
            if not new_texts:
                self.log.info(f"[审查] 内容与库内完全重复，舍弃并删除: {search_keys}")
                self._delete_task(task_dir)
                return 0
        except Exception:
            self.log.exception("检索结果去重异常，继续正常入库")
            new_texts = unit_texts

        by_text = {}
        for u in units:
            by_text.setdefault(u["text"], u)
        sel = [by_text[t] for t in new_texts]

        vectors = self.embedding.embed_texts(new_texts)
        site = str(task_meta.get("site", "") or "")
        base_meta = {
            "source_type": "web",
            "source_id": self._doc_key(first, doc_name, site),
            "doc_name": doc_name,
            "url": str(first.get("url", "") or task_meta.get("url", "")),
            "site": site,
            "tags": str(task_meta.get("search_keys", "")),
        }
        payload = []
        for u in sel:
            m = dict(base_meta)
            m["section"] = str(u.get("section") or "")
            m["section_index"] = str(u.get("section_index") or 0)
            m["chunk_index"] = str(u.get("chunk_index") or 1)
            m["chunk_total"] = str(u.get("chunk_total") or 1)
            payload.append({"text": u["text"], "metadata": m})
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

    @staticmethod
    def _doc_key(first: dict, doc_name: str, site: str) -> str:
        """文档稳定标识（source_id）

        web 来源必须用 url 取指纹：同一页面会在不同搜索词下被反复抓到，只有 url
        稳定；task_id 只是每批的序号（全库只有 "1"~"4"），没有任何标识能力。
        取不到 url 时退化为「站点 + doc_name」，保证仍可复现。
        """
        url = str((first or {}).get("url") or "").strip()
        basis = url if url else f"{site}|{doc_name}"
        return "web_" + hashlib.md5(basis.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _delete_task(task_dir: str):
        """删除重复 task 文件夹（不入库、不入 raw）"""
        try:
            if os.path.isdir(task_dir):
                shutil.rmtree(task_dir, ignore_errors=True)
        except Exception:
            pass

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
