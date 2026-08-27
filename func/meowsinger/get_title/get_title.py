# -*- coding: utf-8 -*-
# func/meowsinger/get_title/get_title.py
# 调用独立 port 提取歌名：优先匹配现有歌名列表，找不到再让 AI 提取用户原意歌名
import os
import difflib

from func.log.default_log import DefaultLog
from func.meowsinger.get_title.title_tool import MeowTitleTool

RAW_DIR = os.path.join("character", "songs", "raw_list")
MEOW_DIR = os.path.join("character", "songs", "meow_list")


class MeowGetTitle:
    """歌名提取：本地匹配现有歌名列表优先，其次 function calling 深度思考"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.tool = MeowTitleTool()

    def list_candidates(self):
        """收集现有歌名（raw_list + meow_list 文件夹名）"""
        cands = set()
        for base in (RAW_DIR, MEOW_DIR):
            if os.path.isdir(base):
                for name in os.listdir(base):
                    if os.path.isdir(os.path.join(base, name)):
                        cands.add(name)
        return sorted(cands)

    def extract(self, text, candidates=None):
        """提取歌名与歌手：本地命中返回 (歌名, "")，否则 AI 提取返回 (歌名, 歌手)"""
        if not text or not text.strip():
            return None, ""
        candidates = candidates or self.list_candidates()

        local = self._local_match(text, candidates)
        if local:
            return local, ""
        return self._ai_extract(text, candidates)

    def _local_match(self, text, candidates):
        """本地匹配：先精确/包含，再 difflib 模糊（阈值 0.5）"""
        if not candidates:
            return None
        stripped = text.strip()
        for cand in candidates:
            if cand and (cand == stripped or cand in stripped or stripped in cand):
                return cand
        best, best_score = None, 0.0
        for cand in candidates:
            score = difflib.SequenceMatcher(None, stripped, cand).ratio()
            if score > best_score:
                best, best_score = cand, score
        return best if best_score >= 0.5 else None

    def _ai_extract(self, text, candidates):
        try:
            from func.meowsinger.port import get_singer_llm
            llm = get_singer_llm()
            if llm is None or not llm.client:
                self.log.error("[GetTitle] meowsinger LLM 不可用")
                return None
            cand_text = "、".join(candidates) if candidates else "（无）"
            system = (
                "你是歌曲名提取助手。仔细阅读用户消息，判断是否包含一首确定要演唱或点播的歌曲名。"
                f"现有歌曲列表：{cand_text}。"
                "优先从现有列表中选最匹配的歌名；若列表中没有，再输出用户原意想点/唱的歌名。"
                "只有歌名明确时才调用工具，模糊（如 随便来一首、唱首歌）或没有歌名时 has_song 填 false。"
            )
            resp = llm.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": text}],
                tools=[self.tool.build_tool()],
            )
            parsed = self.tool.parse(resp)
            if not parsed:
                return None, ""
            title = parsed.get("title") or ""
            artist = parsed.get("artist") or ""
            if title:
                title = self._local_match(title, candidates) or title
            return (title or None), artist
        except Exception:
            self.log.exception("[GetTitle] 歌名提取异常")
            return None, ""
