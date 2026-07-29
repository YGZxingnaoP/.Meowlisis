# -*- coding: utf-8 -*-
"""
记忆管理器：管理短期记忆和长期记忆（基于 BM25 检索）
"""

import os
import threading
import datetime
import re
import math
import jieba
from collections import Counter
from typing import List, Dict, Optional, Callable, Tuple
from .bm25 import BM25


class MemoryManager:
    """记忆管理器，支持短期记忆和长期记忆"""
    
    # jieba 检索黑名单（高频无意义词）
    STOPWORDS = {
        # 已有词
        "主人", "喵呜", "今天", "昨天",

        # 称呼/人称代词
        "你", "我", "他", "她", "它", "我们", "你们", "他们", "她们", "它们",
        "自己", "别人", "大家", "人家",

        # 指示代词
        "这", "那", "这里", "那里", "这边", "那边", "这个", "那个", "这些", "那些",

        # 常见虚词（助词、介词、连词等）
        "的", "了", "在", "是", "有", "和", "与", "或", "而", "且", "也", "就", "都",
        "还", "又", "再", "便", "然后", "但是", "可是", "不过", "因为", "所以", "如果",
        "虽然", "即使", "无论", "不仅", "而且", "以及", "于是", "因此", "否则",

        # 时间词（过于宽泛的）
        "现在", "刚才", "之前", "之后", "将来", "未来", "过去", "同时",

        # 语气词/拟声词
        "啊", "哦", "嗯", "呢", "吧", "吗", "呀", "哇", "哎", "哟", "啦", "呗",
        "呵", "哈", "嘿", "唉", "唔", "噢", "喔",

        # 其他高频常见词（无实际意义）
        "一个", "一种", "这个", "那个", "这些", "那些", "这样", "那样", "这么", "那么",
        "怎么", "什么", "为什么", "如何", "怎样", "哪里", "哪儿", "谁"
    }
    
    # 类变量：共享记忆库
    _shared_memories: List[str] = []
    _shared_bm25: Optional[BM25] = None
    _class_lock = threading.Lock()      # 类级别的锁，保护共享资源
    _dirty = False

    def __init__(self, uid: str, long_term_dir: str = "chatrecords",
                 max_pending_rounds: int = 10, short_term_rounds: int = 3,
                 summary_generator: Optional[Callable[[str], str]] = None):
        """
        记忆管理器
        :param uid: 用户ID，用于区分不同用户的记忆文件
        :param long_term_dir: 长期记忆存储目录
        :param max_pending_rounds: 触发总结的对话轮数
        :param short_term_rounds: 短期记忆保留的对话轮数（用于回复）
        :param summary_generator: 用于生成摘要的函数，接受对话文本，返回摘要字符串
        """
        self.uid = str(uid)
        self.long_term_dir = long_term_dir
        self.max_pending_rounds = max_pending_rounds
        self.short_term_rounds = short_term_rounds
        self.summary_generator = summary_generator

        # 确保目录存在
        os.makedirs(long_term_dir, exist_ok=True)
        self.long_term_file = os.path.join(long_term_dir, "shared_memory.txt")

        # 初始化类变量（只加载一次）
        with MemoryManager._class_lock:
            if not MemoryManager._shared_memories:   # 首次实例化时加载
                self._load_shared_memory()
            # 每个实例自己的 pending_dialogues（仍按用户隔离）
            self.pending_dialogues: List[Dict[str, str]] = []  # 每轮格式 {"user": "xxx", "assistant": "xxx"}

        # 线程锁
        self.lock = threading.Lock()

    def _tokenize(self, text: str) -> List[str]:
        """分词函数，过滤停用词"""
        words = list(jieba.cut(text))
        # 过滤停用词和短词
        filtered = [w for w in words if w not in self.STOPWORDS and len(w) > 1]
        return filtered

    def _load_shared_memory(self):
        """从共享文件加载记忆到类变量，并构建 BM25 索引"""
        if os.path.exists(self.long_term_file):
            with open(self.long_term_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("---"):
                        MemoryManager._shared_memories.append(line)
        # 构建索引
        if MemoryManager._shared_memories:
            MemoryManager._shared_bm25 = BM25(MemoryManager._shared_memories, self._tokenize)
        MemoryManager._dirty = False

    def _save_long_term_memory(self, summary: str):
        """保存一条新的长期记忆到文件"""
        now = datetime.datetime.now()
        date_str = f"{now.year}年{now.month}月{now.day}日"
        line = f"{date_str} - {summary}"
        with MemoryManager._class_lock:
            with open(self.long_term_file, "a", encoding="utf-8") as f:
                f.write(f"\n{line}\n")
            # 更新共享列表
            MemoryManager._shared_memories.append(summary)
            # 标记索引需要重建
            MemoryManager._dirty = True

    def _ensure_index(self):
        """确保 BM25 索引最新（检索前调用）"""
        with MemoryManager._class_lock:
            if MemoryManager._dirty and MemoryManager._shared_memories:
                MemoryManager._shared_bm25 = BM25(MemoryManager._shared_memories, self._tokenize)
                MemoryManager._dirty = False

    def add_user_message(self, message: str, username: str = None):
        """记录用户消息（暂存，等待assistant回复）"""
        self.pending_user_message = message
        if username:
            self.pending_username = username

    def add_assistant_message(self, message: str):
        """记录助手回复，形成完整一轮对话，并处理总结触发"""
        if not hasattr(self, 'pending_user_message'):
            raise RuntimeError("没有待处理的用户消息，请先调用add_user_message")

        # 构建一轮对话
        round_data = {
            "user": self.pending_user_message,
            "assistant": message
        }
        with self.lock:
            self.pending_dialogues.append(round_data)

        # 检查是否需要触发总结（达到max_pending_rounds轮）
        if len(self.pending_dialogues) >= self.max_pending_rounds:
            # 取前max_pending_rounds-1轮用于总结，保留最后一轮
            with self.lock:
                dialogues_to_summarize = self.pending_dialogues[:-1]
                self.pending_dialogues = [self.pending_dialogues[-1]]
            if self.summary_generator and dialogues_to_summarize:
                threading.Thread(target=self._generate_and_save_summary,
                                 args=(dialogues_to_summarize,)).start()

        # 清除暂存
        del self.pending_user_message
        if hasattr(self, 'pending_username'):
            del self.pending_username

    def _generate_and_save_summary(self, dialogues: List[Dict[str, str]]):
        """生成摘要并保存（在后台线程运行）"""
        # 将对话列表格式化为文本
        dialogue_text = ""
        for d in dialogues:
            dialogue_text += f"用户：{d['user']}\n"
            dialogue_text += f"助手：{d['assistant']}\n"

        # 调用摘要生成函数
        summary = self.summary_generator(dialogue_text)
        if summary:
            # 限制长度不超过220字
            if len(summary) > 220:
                summary = summary[:220] + "…"
            self._save_long_term_memory(summary)

    def retrieve(self, query: str, top_k: int = 3) -> List[str]:
        """
        根据用户查询检索最相关的长期记忆
        :param query: 用户消息
        :param top_k: 返回最多 top_k 条记忆
        :return: 相关记忆文本列表（按相关性降序）
        """
        self._ensure_index()
        if not MemoryManager._shared_bm25 or not MemoryManager._shared_memories:
            return []
        
        # 对查询进行分词过滤
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []
        
        query_filtered = " ".join(query_tokens)
        scores = MemoryManager._shared_bm25.get_scores(query_filtered)
        
        # 获取得分大于 0 的索引并按得分排序
        indexed_scores = [(i, score) for i, score in enumerate(scores) if score > 0]
        indexed_scores.sort(key=lambda x: x[1], reverse=True)
        top_indices = [idx for idx, _ in indexed_scores[:top_k]]
        return [MemoryManager._shared_memories[i] for i in top_indices]

    def build_messages(self, current_user_message: str, include_long_term: bool = True, 
                       username: str = None) -> List[Dict[str, str]]:
        """
        构建用于 LLM 的消息列表
        :param current_user_message: 当前用户消息
        :param include_long_term: 是否包含长期记忆
        :param username: 用户名（用于个性化）
        :return: 消息列表（OpenAI 格式）
        """
        messages = []
        
        # 短期记忆（最近几轮对话）
        with self.lock:
            recent_dialogues = self.pending_dialogues[-self.short_term_rounds:] if self.pending_dialogues else []

        for round_data in recent_dialogues:
            messages.append({"role": "user", "content": round_data["user"]})
            messages.append({"role": "assistant", "content": round_data["assistant"]})

        # 插入长期记忆作为背景
        if include_long_term:
            relevant_memories = self.retrieve(current_user_message, top_k=3)
            if relevant_memories:
                # 将多条记忆合并为一段文本
                memory_text = "；".join(relevant_memories)
                # 在对话历史开头插入一条背景记忆消息
                messages.insert(0, {"role": "user", "content": f"[记忆：{memory_text}]"})

        # 添加当前用户消息
        messages.append({"role": "user", "content": current_user_message})
        
        return messages

    def clear(self):
        """清空当前用户的短期记忆（保留长期记忆）"""
        with self.lock:
            self.pending_dialogues = []
            if hasattr(self, 'pending_user_message'):
                del self.pending_user_message
            if hasattr(self, 'pending_username'):
                del self.pending_username

    def get_short_term_history(self, rounds: int = None) -> List[Dict[str, str]]:
        """获取短期记忆历史"""
        if rounds is None:
            rounds = self.short_term_rounds
        with self.lock:
            return self.pending_dialogues[-rounds:] if self.pending_dialogues else []
