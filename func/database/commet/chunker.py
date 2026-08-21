# -*- coding: utf-8 -*-
# func/database/commet/chunker.py
# 文本分块（移植自 Comet app/core/rag/chunker.py，去除外部依赖，保留核心逻辑）

import re

from func.log.default_log import DefaultLog


class CatLearnChunker:
    """文本分块：按中英文句子边界切分，合并到目标 token 数（可带重叠）。

    - 轻量实现：优先用 tiktoken 估算 token，不可用时回退按字符长度估算。
    - 提供父子分块：父块提供上下文，子块用于向量召回。
    """

    CHILD_CHUNK_TOKENS = 256
    PARENT_CHUNK_TOKENS = 1024
    CHILD_OVERLAP_RATIO = 0.1

    _SENT_SEP = re.compile(r"(?<=[。！？\.\!\?\n])")

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._encoder = None
        try:
            import tiktoken
            self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoder = None

    def count_tokens(self, text: str) -> int:
        if self._encoder is not None:
            try:
                return len(self._encoder.encode(text or ""))
            except Exception:
                pass
        # 回退：中文约 1 字 1 token，英文约 4 字符 1 token
        s = text or ""
        return max(1, int(len(s) / 2.4))

    def split_sentences(self, text: str) -> list:
        parts = [s.strip() for s in self._SENT_SEP.split(text or "") if s and s.strip()]
        return parts

    def merge_to_chunks(self, sentences: list, target_tokens: int,
                        overlap_ratio: float = 0.0) -> list:
        """把句子合并成不超过 target_tokens 的块，可带重叠"""
        chunks = []
        cur = []
        cur_tokens = 0
        for sent in sentences:
            st = self.count_tokens(sent)
            if st >= target_tokens:
                if cur:
                    chunks.append("".join(cur))
                    cur, cur_tokens = [], 0
                chunks.append(sent)
                continue
            if cur_tokens + st > target_tokens and cur:
                chunks.append("".join(cur))
                if overlap_ratio > 0:
                    keep = max(1, int(len(cur) * overlap_ratio))
                    cur = cur[-keep:]
                    cur_tokens = sum(self.count_tokens(s) for s in cur)
                else:
                    cur, cur_tokens = [], 0
            cur.append(sent)
            cur_tokens += st
        if cur:
            chunks.append("".join(cur))
        return chunks

    def chunk(self, text: str, target_tokens: int = None, overlap_ratio: float = 0.0) -> list:
        """简单分块：按目标 token 数切分，返回文本块列表"""
        text = (text or "").strip()
        if not text:
            return []
        target = target_tokens or self.CHILD_CHUNK_TOKENS
        sentences = self.split_sentences(text)
        return self.merge_to_chunks(sentences, target, overlap_ratio)

    def chunk_parent_child(self, text: str) -> list:
        """父子分块：返回 [{"parent": str, "children": [str, ...]}, ...]"""
        text = (text or "").strip()
        if not text:
            return []
        sentences = self.split_sentences(text)
        parent_contents = self.merge_to_chunks(sentences, self.PARENT_CHUNK_TOKENS)
        result = []
        for pc in parent_contents:
            child_sents = self.split_sentences(pc)
            children = self.merge_to_chunks(child_sents, self.CHILD_CHUNK_TOKENS, self.CHILD_OVERLAP_RATIO)
            result.append({"parent": pc, "children": children})
        return result
