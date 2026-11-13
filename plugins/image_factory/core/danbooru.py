# -*- coding: utf-8 -*-
"""danbooru 角色 tag 解析：中文名/英文名 → 官方 tag（如 `chiz (nte)`）。

生图模型（MOSS / Anima）都没那么落后，知道绝大多数角色——关键是**给对 tag**。
流程：
  1. 有英文名（人工表/萌百/LLM）→ 用 danbooru 的 tag 搜索接口找候选；
  2. 候选里优先「带作品括注」且匹配英文名的，其次取 count 最高的；
  3. 结果缓存到 data/danbooru_tags.json，避免每次重复请求。
"""

import json
import os
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
      "Accept": "application/json"}
API = "https://danbooru.donmai.us/tags.json"


def _get(url, timeout=12):
    """带 UA 的 GET，返回 bytes。"""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def _norm(s):
    """tag 归一：小写、下划线转空格。"""
    return re.sub(r"[_\s]+", " ", str(s or "").strip().lower())


class DanbooruTags:
    """角色 tag 解析 + 本地缓存（查不到/连不上就跳过，绝不阻塞出图）"""

    def __init__(self, cache_file, log=None, enabled=True, timeout=12):
        """记录缓存路径、开关与超时。"""
        self.cache_file = str(cache_file or "")
        self.log = log
        self.enabled = bool(enabled)
        self.timeout = max(3, int(timeout or 12))
        self._cache = None

    # ---------- 缓存 ----------
    def _load(self):
        """载入 tag 缓存。"""
        if self._cache is not None:
            return
        self._cache = {}
        if self.cache_file and os.path.isfile(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._cache = {str(k): str(v) for k, v in data.items() if v}
            except Exception:
                pass

    def _save(self):
        """写回 tag 缓存。"""
        if not self.cache_file:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception:
            if self.log:
                self.log.warning("[image_factory] tag 缓存写入失败")

    # ---------- 查询 ----------
    def search(self, en_name, series_hint="", limit=20):
        """en_name 是英文名（如 chiz / mika）；返回候选 tag 列表"""
        q = urllib.parse.urlencode({
            "search[name_matches]": "%s*" % str(en_name).strip(),
            "search[order]": "count",
            "limit": limit,
        })
        try:
            data = json.loads(_get(API + "?" + q, timeout=self.timeout))
        except Exception as e:
            if self.log:
                self.log.info("[image_factory] danbooru 查询失败(%s)，用本地/人工结果"
                              % type(e).__name__)
            return []
        out = []
        for item in (data if isinstance(data, list) else []):
            name = str(item.get("name") or "").replace("_", " ")
            if not name:
                continue
            out.append({"name": name, "count": int(item.get("post_count") or 0),
                        "category": int(item.get("category") or 0)})
        return out

    def resolve(self, cn_name, en_name="", series_hint=""):
        """返回最合适的 danbooru tag；关掉/查不到/连不上都返回空串"""
        if not self.enabled:
            return ""
        self._load()
        key = "%s|%s" % (cn_name, series_hint)
        if key in self._cache:
            return self._cache[key]
        if cn_name in self._cache:
            return self._cache[cn_name]

        tag = ""
        en = _norm(en_name)
        hint = _norm(series_hint)
        if en:
            cands = self.search(en)
            if cands:
                # 1) 英文名完全一致 + 作品括注匹配
                def score(c):
                    """候选 tag 的打分函数。"""
                    n = _norm(c["name"])
                    s = 0
                    if n == en:
                        s += 100
                    elif n.startswith(en + " "):
                        s += 60
                    elif en in n:
                        s += 30
                    if hint and hint in n:
                        s += 80
                    if "(" in n:
                        s += 10
                    return s + min(c["count"], 5000) / 5000.0

                cands.sort(key=score, reverse=True)
                best = cands[0]
                if score(best) >= 30:
                    tag = best["name"]
                    if self.log:
                        self.log.info("[image_factory] danbooru tag: %s → %s（%d 图）"
                                      % (cn_name, tag, best["count"]))
        if tag:
            self._cache[key] = tag
            self._cache.setdefault(cn_name, tag)
            self._save()
        return tag
