# -*- coding: utf-8 -*-
# func/database/database_core.py
# database 核心：数据初始化与数据传输、关键词匹配、信息汇总到 system_prompt

import threading

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.config import CatLearnConfig
from func.database.alluser_record import CatLearnAllUserRecord


@singleton
class CatLearnCore:
    """database 核心（单例）

    两条路径：
    A. 消息记录路径 on_message()（由 pipeline/msg_database 桥接异步调用）：
       1) 记录 user 消息到 alluser_record；
       2) 否定词拦截优先；
       3) 命中"搜索"关键词 → 异步调用 search 模块（keyword 触发，结果摘要一次性）；
       4) alluser_record 滚动 → 异步调用 search 模块（record 触发，深度思考决策，结果入库）。
    B. 提示词构建路径 build_knowledge_prompt()（由 system_prompt/prompt_builder 同步调用）：
       1) 命中"知道/了解"关键词 → 同步提取 keys 检索知识库（15 条），插入当轮提示词；
       2) 读取该用户的一次性网络搜索摘要（读后即清）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CatLearnConfig()
        self.record = CatLearnAllUserRecord()
        self._lock = threading.Lock()

    # ==================== 初始化 ====================
    def init(self):
        """项目启动时初始化：commet（向量库 + 文档入库扫描）"""
        try:
            from func.database.commet.core import CatLearnCommet
            CatLearnCommet().init()
        except Exception:
            self.log.exception("database_core 初始化异常")

    # ==================== A. 消息记录路径 ====================
    def on_message(self, text: str, username: str):
        """接收一条消息：记录 + 搜索关键词触发 + 滚动触发（异步桥接层调用）"""
        text = (text or "").strip()
        if not text:
            return
        username = username or "匿名"

        # 1. 记录用户消息（滚动时返回 True）
        try:
            rolled = self.record.record_user_message(username, text)
        except Exception:
            self.log.exception("记录 alluser_record 失败")
            rolled = False

        # 2. 否定词拦截优先
        if self._is_negated(text):
            return

        # 3. 搜索关键词 → 异步触发搜索（结果摘要一次性）
        if self._match_keywords(text, self.config.search_keywords):
            self.log.info(f"[database] 用户 {username} 命中搜索关键词: {text[:30]}")
            try:
                from func.database.search.search_core import CatLearnSearch
                CatLearnSearch().start_search(text, username, "keyword")
            except Exception:
                self.log.exception("关键词搜索触发异常")
            return

        # 4. alluser_record 滚动 → 核心 search 决策（结果入库）
        if rolled:
            try:
                full = self.record.full_text()
                if full.strip():
                    self.log.info("[database] alluser_record 滚动，触发核心 search 决策")
                    from func.database.search.search_core import CatLearnSearch
                    CatLearnSearch().start_search(full, username, "record")
            except Exception:
                self.log.exception("核心 search 决策触发异常")

    # ==================== B. 提示词构建路径 ====================
    def build_knowledge_prompt(self, username: str = "", current_message: str = "") -> str:
        """汇总知识库提示词（同步，供 system_prompt 拼接）

        - 命中"知道/了解"关键词：同步检索知识库（15 条，截断100字）；
        - 普通消息（非否定、非搜索）：默认检索知识库（5 条，截断50字）；
        - 命中"搜索"关键词：不做知识库检索（搜索摘要异步处理，一次性）；
        - 读取该用户一次性网络搜索摘要（读后即清）。
        返回 markdown 文本，无内容返回空串。
        """
        parts = []

        msg = (current_message or "").strip()
        if msg and not self._is_negated(msg) and not self._match_keywords(msg, self.config.search_keywords):
            keyword_trigger = self._match_keywords(msg, self.config.know_keywords)
            try:
                kb = self._retrieve_knowledge(msg, keyword_trigger=keyword_trigger)
                if kb:
                    parts.append(kb)
            except Exception:
                self.log.exception("知识库同步检索失败")

        # 一次性网络搜索摘要（按用户读取，读后即清）
        if username:
            try:
                from func.database.search.search_understand import CatLearnSearchUnderstand
                summary = CatLearnSearchUnderstand().take_result(username)
                if summary:
                    parts.append(summary)
            except Exception:
                self.log.exception("读取网络搜索摘要失败")

        return "\n\n".join([p for p in parts if p])

    # ==================== 关键词匹配 ====================
    def _match_keywords(self, text: str, keywords: list) -> bool:
        for kw in keywords or []:
            if kw and kw in text:
                return True
        return False

    def _is_negated(self, text: str) -> bool:
        """否定词拦截：命中任一否定词返回 True（优先级最高）"""
        return self._match_keywords(text, self.config.neg_keywords)

    # ==================== 知识库检索 ====================
    def _retrieve_knowledge(self, text: str, keyword_trigger: bool = False) -> str:
        """提取 keys → 检索 → 构建知识库提示词

        keyword_trigger=True 检索 15 条、截断 100 字；否则检索 5 条、截断 50 字。
        """
        from func.database.store.searching import CatLearnSearching
        from func.database.store.build_prompt import CatLearnBuildPrompt
        keys = CatLearnSearching().extract_keys(text)
        if not keys:
            return ""
        top_k = self.config.store_keyword_top_k if keyword_trigger else self.config.store_top_k
        return CatLearnBuildPrompt().build(keys, top_k=top_k, keyword_trigger=keyword_trigger)
