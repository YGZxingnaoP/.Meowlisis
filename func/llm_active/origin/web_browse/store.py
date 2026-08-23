# -*- coding: utf-8 -*-
# func/llm_active/origin/web_browse/store.py
# 缓存 JSON 落盘 / 文件命名清洗 / 消费后移动收藏 / 缓存计数

import hashlib
import json
import os
import re
from typing import Dict, List

from func.log.default_log import DefaultLog
from func.llm_active.origin.web_browse.config import AutoWebBrowseConfig


class AutoBrowseStore:
    """管理 web_browse 缓存 json 的读写与移动"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = AutoWebBrowseConfig()

    # ==================== 保存 ====================
    def save(self, item: Dict) -> str:
        """把视频摘要 json 写入缓存目录，返回文件绝对路径"""
        os.makedirs(self.config.cache_dir, exist_ok=True)
        path = os.path.join(self.config.cache_dir, self._filename(item.get("title", "")))
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception(f"[WebBrowse] 写缓存失败: {path}")
            return ""
        return os.path.abspath(path)

    # ==================== 消费后移动收藏 ====================
    def move_to_collect(self, path: str) -> str:
        """把已消费的 json 移到 character/shared_videos 收藏，返回新路径"""
        if not path or not os.path.exists(path):
            return ""
        os.makedirs(self.config.collect_dir, exist_ok=True)
        dest = os.path.join(self.config.collect_dir, os.path.basename(path))
        try:
            os.replace(path, dest)
            return os.path.abspath(dest)
        except Exception:
            self.log.exception(f"[WebBrowse] 移动收藏失败: {path}")
            return ""

    # ==================== 缓存查询 ====================
    def list_cache(self) -> List[str]:
        """列出缓存目录下所有 json（按文件名排序，供随机池使用）"""
        if not os.path.isdir(self.config.cache_dir):
            return []
        try:
            files = [
                os.path.join(self.config.cache_dir, f)
                for f in os.listdir(self.config.cache_dir)
                if f.endswith(".json")
            ]
            files.sort()
            return files
        except Exception:
            self.log.exception("[WebBrowse] 列出缓存失败")
            return []

    def count_cache(self) -> int:
        """当前缓存 json 数量"""
        return len(self.list_cache())

    def is_full(self) -> bool:
        """缓存是否已达上限"""
        return self.count_cache() >= self.config.max_cache

    # ==================== 文件名清洗 ====================
    @staticmethod
    def _clean_title(title: str) -> str:
        """去除非法文件名字符与空白，截断到 10 字符"""
        s = str(title or "").strip()
        s = re.sub(r'[\\/:*?"<>|\r\n\t]', '', s)
        s = re.sub(r'\s+', '', s)
        if not s:
            s = "video"
        return s[:10]

    @classmethod
    def _filename(cls, title: str) -> str:
        """{清洗后标题10字符}_{md5前6位}.json"""
        clean = cls._clean_title(title)
        digest = hashlib.md5(str(title or "").encode("utf-8")).hexdigest()[:6]
        return f"{clean}_{digest}.json"
