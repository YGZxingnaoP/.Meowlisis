# -*- coding: utf-8 -*-
# func/database/store/port/bge.py
# 硅基流动 BAAI/bge-m3 文本向量端口（统一文本 embedding，不处理图片）

import requests

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.config import CatLearnConfig


@singleton
class CatLearnEmbedding:
    """硅基流动 bge-m3 文本向量客户端（单例）

    - 所有入库内容（网页文本 / 文档文本）统一走 bge-m3 文本向量；
    - 图片内容已按需求排除，仅对文本调用。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CatLearnConfig()
        self.api_key = self.config.embedding_api_key
        self.base_url = self.config.embedding_base_url.rstrip("/")
        self.model = self.config.embedding_model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def embed_texts(self, texts: list) -> list:
        """批量文本向量化，返回 list[list[float]]（顺序与输入一致）"""
        if not texts:
            return []
        if not self.available:
            self.log.error("硅基流动 embedding API Key 未配置")
            return []
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": [str(t) for t in texts], "model": self.model},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self.log.error(f"embedding 调用异常: {e}")
            return []
        try:
            items = data.get("data") or []
            items_sorted = sorted(items, key=lambda x: x.get("index", 0))
            return [list(item.get("embedding") or []) for item in items_sorted]
        except Exception:
            self.log.exception("embedding 响应解析失败")
            return []

    def embed_one(self, text: str) -> list:
        """单条文本向量化，返回 list[float]（失败返回空列表）"""
        vecs = self.embed_texts([text])
        return vecs[0] if vecs and vecs[0] else []
