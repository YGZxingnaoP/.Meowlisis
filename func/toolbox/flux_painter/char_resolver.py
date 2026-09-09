# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/char_resolver.py
"""点名角色解析：把中文角色名解析为 Anima 可识别的 tag/资料。

三级查找（模块化、可独立调用）：
  1) 本地词典  .ComfyNode/prompt_reference/role_map.json
       人工维护：主键=中文常用名，aliases=别名，tags=danbooru 风格角色标签，en/appearance 可空
  2) 解析缓存  .ComfyNode/prompt_reference/role_cache.json（moegirl 结果缓存 7 天）
  3) 萌娘百科  仅当上面都未命中且 LLM 表示不了解（character_known=false）才访问：
        opensearch 取官方条目名 → 抓条目 HTML 尽量提取英文名/发色/瞳色
  全程短超时+静默降级，失败返回 None，不影响主流程。

用法：
    r = TBRoleResolver(cfg)
    card = r.resolve("阿尔托莉雅")     # -> {name, en, tags[], appearance, known} | None
    print(r.card_text(card))           # 拼给 LLM 的角色资料段
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

from func.log.default_log import DefaultLog

MOEGIRL_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
CACHE_TTL = 7 * 24 * 3600


class TBRoleResolver:
    def __init__(self, config):
        self.config = config
        self.log = DefaultLog().getLogger()
        self._map = None

    # ==================== 本地词典 ====================
    def _load_map(self):
        """role_map.json → {alias_lower: entry}（key 与 aliases 均建索引）"""
        if self._map is None:
            idx = {}
            try:
                raw = json.load(open(self.config.role_map_file, "r", encoding="utf-8"))
            except Exception:
                raw = {}
            for name, entry in (raw or {}).items():
                if not isinstance(entry, dict):
                    entry = {}
                keys = [name] + [a for a in (entry.get("aliases") or []) if isinstance(a, str)]
                for k in keys:
                    k = str(k).strip()
                    if k:
                        idx[k.lower()] = {"name": name, "entry": entry}
            self._map = idx
        return self._map

    def _map_hit(self, character):
        """词典命中：character 包含别名 或 别名包含 character（短称呼）"""
        idx = self._load_map()
        c = str(character or "").strip().lower()
        if not c:
            return None
        for alias, item in idx.items():
            if alias == c or alias in c or (len(alias) >= 2 and c in alias):
                return item
        return None

    # ==================== 缓存 ====================
    def _load_cache(self):
        try:
            return json.load(open(self.config.role_cache_file, "r", encoding="utf-8"))
        except Exception:
            return {}

    def _save_cache(self, cache):
        try:
            os.makedirs(os.path.dirname(self.config.role_cache_file), exist_ok=True)
            json.dump(cache, open(self.config.role_cache_file, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _cache_hit(self, key):
        cache = self._load_cache()
        item = cache.get(key)
        if item and isinstance(item, dict) and (time.time() - float(item.get("ts") or 0)) < CACHE_TTL:
            return item.get("card")
        return None

    def _cache_set(self, key, card):
        try:
            cache = self._load_cache()
            cache[key] = {"ts": time.time(), "card": card}
            self._save_cache(cache)
        except Exception:
            pass

    # ==================== 萌娘百科（仅出网） ====================
    def _http(self, url, timeout=6):
        req = urllib.request.Request(url, headers=MOEGIRL_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")

    def _moe_search(self, character):
        """opensearch 取官方条目标题列表（可用性已验证），失败返回 []"""
        try:
            url = "https://zh.moegirl.org.cn/api.php?" + urllib.parse.urlencode({
                "action": "opensearch", "search": character, "limit": 3, "format": "json"})
            data = json.loads(self._http(url))
            return [str(t) for t in (data[1] if len(data) > 1 else []) if str(t).strip()]
        except Exception:
            return []

    def _moe_features(self, title):
        """抓条目 HTML 尽力提取 英文名/罗马音/发色/瞳色（失败仅返回 title）"""
        try:
            html = self._http("https://zh.moegirl.org.cn/" + urllib.parse.quote(title))
        except Exception:
            return {}
        feats = {}
        # 信息框字段：形态 <th>发色</th>…<td>金色</td> 或模板内 |发色=金发
        pats = {"en": [r"英文名[^<]{0,20}?<[^>]*>([A-Za-z][^<>]{1,60}?)(?:<|，|；|、)",
                       r"罗马音[^<]{0,20}?<[^>]*>([A-Za-z][^<>]{1,60}?)(?:<|，|；|、)"],
                "hair": [r"(?:发色|发色为)[^<]{0,20}?<[^>]*>([^<>]{1,20}?)(?:<|（|，|；|、)"],
                "eyes": [r"瞳色[^<]{0,20}?<[^>]*>([^<>]{1,20}?)(?:<|（|，|；|、)"]}
        for k, ps in pats.items():
            for p in ps:
                m = re.search(p, html)
                if m:
                    v = re.sub(r"<[^>]+>|\[\[|\]\]|\{\{|\}\}", "", m.group(1)).strip()
                    if v:
                        feats[k] = v[:40]
                        break
        return feats

    def _search_moegirl(self, character):
        """出网解析：返回 card dict 或 None"""
        titles = self._moe_search(character)
        if not titles:
            return None
        title = titles[0]
        feats = self._moe_features(title)
        card = {"name": title, "source": "moegirl"}
        if feats.get("en"):
            card["en"] = feats["en"]
        if feats.get("hair"):
            card["appearance"] = f"发色{feats['hair']}"
        if feats.get("eyes"):
            card["appearance"] = (card.get("appearance", "") + f"，瞳色{feats['eyes']}").lstrip("，")
        return card

    # ==================== 对外入口 ====================
    def resolve(self, character, allow_net=True):
        """解析点名角色。返回 card dict：
        {name, en?, tags?, appearance?, known}；无资料返回 None（主流程原样走 LLM）"""
        c = str(character or "").strip()
        if not c:
            return None
        hit = self._map_hit(c)
        if hit:
            entry = hit["entry"]
            card = {"name": entry.get("name") or hit["name"], "known": True, "source": "map"}
            tags = [t for t in (entry.get("tags") or []) if str(t).strip()]
            if tags:
                card["tags"] = tags
            if entry.get("en"):
                card["en"] = str(entry["en"])
            if entry.get("appearance"):
                card["appearance"] = str(entry["appearance"])
            return card
        cached = self._cache_hit(c)
        if cached:
            cached = dict(cached)
            cached.setdefault("known", True)
            cached["from_cache"] = True
            return cached
        if not (allow_net and self.config.moegirl_lookup):
            return None
        card = self._search_moegirl(c)
        if card:
            card.setdefault("known", False)
            self._cache_set(c, card)
        return card

    def card_text(self, card, limit=420):
        """把资料卡拼成给 LLM 的角色资料段（无 en/tags 时提示按官方名考据）"""
        if not card:
            return ""
        parts = [f"角色官方名：{card.get('name', '')}"]
        if card.get("en"):
            parts.append(f"英文名：{card['en']}")
        if card.get("tags"):
            parts.append("推荐角色标签：" + ", ".join(card["tags"]))
        if card.get("appearance"):
            parts.append("外观：" + card["appearance"])
        text = "；".join(parts)
        return "【点名角色资料卡】" + text[:limit] + "（若资料有限，请以该角色公认特征补全标签）"
