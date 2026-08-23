# -*- coding: utf-8 -*-
# func/database/store/port：embedding 端口（阿里云 DashScope / 硅基流动 BGE）

from func.database.config import CatLearnConfig


def get_embedding():
    """按配置返回文本向量客户端。

    - provider == 'aliyun'：阿里云 DashScope qwen3.7-text-embedding；
    - 其它：硅基流动 BAAI/bge-m3。
    """
    cfg = CatLearnConfig()
    if cfg.embedding_provider == "aliyun":
        from func.database.store.port.aliyun import CatLearnAliyunEmbedding
        return CatLearnAliyunEmbedding()
    from func.database.store.port.bge import CatLearnEmbedding
    return CatLearnEmbedding()
