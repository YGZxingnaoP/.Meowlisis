# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/comfy_connector/artist.py
import json
import os
import random
import re

from func.log.default_log import DefaultLog

ARTIST_SRC_ENV = "FLUXPAINTER_ARTIST_SRC"
# 风格化随机抽画师的质量门槛：
#   ARTIST_RANDOM_MIN_POSTS  只抽 danbooru 作品数达标的画师（太冷门的模型基本没学到）
#   ARTIST_RANDOM_MAX_POOL   只在前 N 名热门画师里随机（data.js 已按 post_count 降序，N 名=池子大小）
#   ARTIST_RANDOM_EXCLUDE    剔除匿名/占位类伪画师 tag（drawfag 等本身不携带画风）
ARTIST_RANDOM_MIN_POSTS = 500
ARTIST_RANDOM_MAX_POOL = 2000
ARTIST_RANDOM_EXCLUDE = re.compile(r"drawfag|anonymous", re.IGNORECASE)


def _norm_name(s):
    """名字归一化：去掉转义反斜杠、括号、下划线、空格与连字符，便于模糊点名"""
    return re.sub(r"[\s_\-\\()（）]", "", str(s or "").lower())

# 画师库源文件搜索顺序：环境变量 → 项目内副本(.ComfyNode/artist/data.js) → 旧外置路径（兼容保留）
ARTIST_SRC_FALLBACK = (r"D:\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes"
                       r"\Comfyui-Anima-Tools-main\js\data.js")


def artist_src_path(config=None):
    """画师库源路径（自包含优先，不再硬依赖 D:\\ComfyUI）"""
    env = os.environ.get(ARTIST_SRC_ENV, "").strip()
    if env and os.path.isfile(env):
        return env
    if config is not None:
        node_dir = getattr(config, "comfy_node_dir", "") or ""
        for rel in (os.path.join("artist", "data.js"),):
            p = os.path.join(node_dir, rel)
            if os.path.isfile(p):
                return p
        cfg_src = (getattr(config, "comfy", {}) or {}).get("artist_src") if isinstance(
            getattr(config, "comfy", None), dict) else None
        if cfg_src and os.path.isfile(str(cfg_src)):
            return str(cfg_src)
    return ARTIST_SRC_FALLBACK


class TBArtistPicker:
    """画师库（danbooru 画师 data.js）拷贝/检索/默认风格拼接"""

    def __init__(self, config):
        self.config = config
        self.log = DefaultLog().getLogger()
        self._cache = None

    def ensure_data(self):
        """本地画师库缺失时从内置副本/环境变量拷贝一份，返回 (ok, 说明)"""
        path = self.config.artist_data
        if os.path.isfile(path):
            return True, "画师库就绪"
        src = artist_src_path(self.config)
        if not os.path.isfile(src):
            return False, (f"画师库源缺失: {src}"
                           f"（可放到 .ComfyNode/artist/data.js 或设 {ARTIST_SRC_ENV}）")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(src, "r", encoding="utf-8") as f:
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
        """按名字检索画师（点名用）：精确名 > 归一化精确 > 子串；返回 [{name, id, post_count}]

        归一化 = 去掉 \\( \\) 、下划线、空格，这样 'hara harayutaka' 也能命中
        库里的 'hara \\(harayutaka\\)'。"""
        kw = (keyword or "").strip().lower()
        if not kw:
            return []
        kwn = _norm_name(kw)
        exact, nrm, subs = [], [], []
        for a in self._load():
            name = (a.get("name") or "").lower()
            if name == kw:
                exact.append(a)
                continue
            nm = _norm_name(name)
            if kwn and nm == kwn:
                nrm.append(a)
            elif kw in name or (kwn and kwn in nm):
                subs.append(a)
        for lst in (exact, nrm, subs):
            lst.sort(key=lambda x: x.get("post_count") or 0, reverse=True)
        return (exact + nrm + subs)[:top]

    def random_pool(self):
        """风格化随机池：按 post_count 过滤 + 剔除匿名/占位画师，返回条目列表

        data.js 本身按 post_count 降序分页（每页 1000），所以『前 N 名』= 最热门 N 位，
        随机命中率高的同时保证模型认识这位画师。池子为空时回退全库（绝不空手）。"""
        pool = [a for a in self._load()
                if (a.get("post_count") or 0) >= ARTIST_RANDOM_MIN_POSTS
                and not ARTIST_RANDOM_EXCLUDE.search(a.get("name") or "")]
        if not pool:
            pool = [a for a in self._load()
                    if not ARTIST_RANDOM_EXCLUDE.search(a.get("name") or "")]
        return pool[:ARTIST_RANDOM_MAX_POOL] or list(self._load())

    def pick_artists(self, count=1):
        """从画师库随机挑 count 名（走 random_pool 的质量过滤）"""
        pool = self.random_pool()
        if not pool:
            return []
        return random.sample(pool, min(count, len(pool)))

    def build_artist_tags(self, named=None, style_tags=None, count=1):
        """拼画师串：@点名画师 + 随机补位 + 可选风格串，返回如 '@a, @b, @style, '

        注：生产已改为"默认不加画师"，未点名/未要求风格化时不会走到这里；
        style_tags 显式传入才追加（配置项 default_style 已移除）。
        """
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
        for s in (style_tags or []):
            s = (s or "").strip()
            if s and s not in tags:
                tags.append(s)
        return ", ".join(tags) + ", " if tags else ""
