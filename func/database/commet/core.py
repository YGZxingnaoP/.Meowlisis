# -*- coding: utf-8 -*-
# func/database/commet/core.py
# commet 模块初始化入口（项目启动时调用，初始化 RAG 纯逻辑 + 文档入库扫描）

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class CatLearnCommet:
    """commet 模块核心（单例）：启动时初始化向量库并扫描 inbox 文档入库"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def init(self):
        """初始化：确保向量库就绪，并扫描 .DataBase/inbox 文档入库"""
        try:
            from func.database.store.vector_db import CatLearnVectorDB
            vdb = CatLearnVectorDB()
            if not vdb.available:
                self.log.error("ChromaDB 知识库不可用，commet 初始化跳过")
                return

            from func.database.commet.learning_doc import CatLearnDocLearning
            count = CatLearnDocLearning().scan_and_learn()
            if count:
                self.log.info(f"commet 初始化完成，文档入库 {count} 条")
            else:
                self.log.info("commet 初始化完成（inbox 无待入库文档）")
        except Exception:
            self.log.exception("commet 初始化异常")
