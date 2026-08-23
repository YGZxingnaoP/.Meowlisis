# -*- coding: utf-8 -*-
# func/database/store/port/aliyun.py
# 阿里云 DashScope qwen3.7-text-embedding 文本向量端口

from http import HTTPStatus

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.config import CatLearnConfig


@singleton
class CatLearnAliyunEmbedding:
    """阿里云 DashScope 文本向量客户端（单例）

    - 模型：qwen3.7-text-embedding；
    - 维度可配置（默认 1024），通过 dashscope.TextEmbedding.call 的 dimension 传入；
    - 输入统一为文本列表，输出 list[list[float]]（顺序与输入一致）。
    """

    BATCH_SIZE = 10  # qwen3.7-text-embedding 官方示例按 10 条一批处理

    def __init__(self):
        self.log = DefaultLog().getLogger()
        cfg = CatLearnConfig()
        self.api_key = cfg.embedding_aliyun_api_key
        self.base_url = cfg.embedding_aliyun_base_url
        self.model = cfg.embedding_aliyun_model
        self.dimension = cfg.embedding_dimension

        # 指定地域/业务空间时可通过 base_url 覆盖默认 DashScope endpoint
        if self.base_url:
            try:
                import dashscope
                dashscope.base_http_api_url = self.base_url.rstrip("/")
            except Exception:
                pass

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def embed_texts(self, texts: list) -> list:
        """批量文本向量化，返回 list[list[float]]（顺序与输入一致）"""
        if not texts:
            return []
        if not self.available:
            self.log.error("阿里云 DashScope embedding API Key 未配置")
            return []
        try:
            import dashscope
        except Exception as e:
            self.log.error(f"dashscope 未安装: {e}")
            return []

        flat = [str(t) for t in texts]
        results = []
        for i in range(0, len(flat), self.BATCH_SIZE):
            batch = flat[i:i + self.BATCH_SIZE]
            vecs = self._embed_batch(dashscope, batch)
            if len(vecs) != len(batch):
                self.log.error("dashscope embedding 返回数量不一致，放弃本批结果")
                return []
            results.extend(vecs)
        return results

    def _embed_batch(self, dashscope, batch: list) -> list:
        try:
            kwargs = {
                "model": self.model,
                "input": batch,
                "dimension": self.dimension,
            }
            if self.api_key:
                kwargs["api_key"] = self.api_key
            resp = dashscope.TextEmbedding.call(**kwargs)
        except Exception as e:
            self.log.error(f"dashscope embedding 调用异常: {e}")
            return []

        if getattr(resp, "status_code", None) != HTTPStatus.OK:
            self.log.error(
                f"dashscope embedding 失败: code={getattr(resp, 'code', '')} "
                f"message={getattr(resp, 'message', '')}"
            )
            return []
        try:
            output = getattr(resp, "output", None) or {}
            items = output.get("embeddings") or []
            if not items:
                # 单条兼容：部分版本返回 output.embedding
                single = output.get("embedding")
                if single:
                    return [list(single)]
                return []
            items_sorted = sorted(
                items,
                key=lambda x: x.get("text_index", 0) if isinstance(x, dict) else 0,
            )
            return [list((item.get("embedding") or [])) for item in items_sorted]
        except Exception:
            self.log.exception("dashscope embedding 响应解析失败")
            return []

    def embed_one(self, text: str) -> list:
        """单条文本向量化，返回 list[float]（失败返回空列表）"""
        vecs = self.embed_texts([text])
        return vecs[0] if vecs and vecs[0] else []
