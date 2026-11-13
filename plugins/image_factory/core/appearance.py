# -*- coding: utf-8 -*-
"""人工外观表：覆盖模型瞎编的外观（优先级最高）。

文件：plugins/image_factory/data/appearance.json
  key 支持「主题/角色」或「角色」，value 是英文外观描述，直接进 caption。
查不到就返回空串，交给后面的百科/LLM 兜底。
"""

import json
import os


class AppearanceBook:
    """人工外观表：命中就用表里的外观，避免模型编错配色。"""
    def __init__(self, path, log=None):
        """记录表路径与日志。"""
        self.path = str(path or "")
        self.log = log
        self._data = None

    def _load(self):
        """惰性载入外观表（支持「主题/角色」与「角色」两种键）。"""
        if self._data is not None:
            return
        self._data = {}
        if not self.path or not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            if self.log:
                self.log.warning("[image_factory] 外观表读取失败: %s" % self.path)
            return
        if isinstance(data, dict):
            self._data = {str(k).strip(): str(v).strip()
                          for k, v in data.items()
                          if str(k).strip() and str(v).strip() and not str(k).startswith("_")}
            if self.log:
                self.log.info("[image_factory] 人工外观表载入 %d 条" % len(self._data))

    def get(self, theme, character):
        """查询角色外观；没有返回空串。"""
        self._load()
        if not self._data:
            return ""
        for key in ("%s/%s" % (theme or "", character), str(character or "")):
            if key and key in self._data:
                return self._data[key]
        return ""
