# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/comfy_connector/artist.py
import json
import os
import random
import re

from func.log.default_log import DefaultLog

ARTIST_SRC = (r"D:\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes"
              r"\Comfyui-Anima-Tools-main\js\data.js")


class TBArtistPicker:
    """画师库（danbooru 画师 data.js）拷贝/检索/默认风格拼接"""

    def __init__(self, config):
        self.config = config
        self.log = DefaultLog().getLogger()
        self._cache = None

    def ensure_data(self):
        """本地画师库缺失时从便携版拷贝一份，返回 (ok, 说明)"""
        path = self.config.artist_data
        if os.path.isfile(path):
            return True, "画师库就绪"
        if not os.path.isfile(ARTIST_SRC):
            return False, f"画师库源缺失: {ARTIST_SRC}"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(ARTIST_SRC, "r", encoding="utf-8") as f:
            with open(path, "w", encoding="utf-8") as g:
                g.write(f.read())
        return True, f"画师库已拷贝: {path}"

    def _load(self):
        """载入画师库（内存缓存一次）"""
        if self._cache is None:
            path = self.config.artist_data
            if not os.path.isfile(path):
                self.ensure_data()
            text = open(path, "r", encoding="utf-8", errors="ignore").read()
            start = text.find("[")
            end = text.rfind("]")
            raw = text[start:end + 1] if start >= 0 and end > start else "[]"
            self._cache = json.loads(raw)
        return self._cache

    def search(self, keyword, top=5):
        """按名字/词检索画师，返回 [{name, id, post_count}]"""
        kw = (keyword or "").strip().lower()
        if not kw:
            return []
        hits = []
        for a in self._load():
            name = (a.get("name") or "").lower()
            if kw in name:
                hits.append(a)
            if len(hits) >= top * 3:
                break
        hits.sort(key=lambda x: x.get("post_count") or 0, reverse=True)
        return hits[:top]

    def pick_artists(self, count=1):
        """从画师库随机挑选 count 名画师（返回条目列表）"""
        pool = self._load()
        if not pool:
            return []
        return random.sample(pool, min(count, len(pool)))

    def build_artist_tags(self, named=None, style_tags=None, count=1):
        """拼画师串：@点名画师 + 随机补位 + 默认画风串，返回如 '@a, @b, @style, '"""
        tags = []
        if named:
            for a in named:
                nm = (a.get("name") or "").strip()
                if nm:
                    tags.append("@" + nm)
        need = max(0, count - len(tags))
        if need > 0:
            for a in self.pick_artists(need):
                nm = (a.get("name") or "").strip()
                if nm and "@" + nm not in tags:
                    tags.append("@" + nm)
        for s in (style_tags or self.config.default_style):
            s = (s or "").strip()
            if s and s not in tags:
                tags.append(s)
        return ", ".join(tags) + ", " if tags else ""
