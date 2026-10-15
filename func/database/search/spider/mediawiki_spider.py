# -*- coding: utf-8 -*-
# func/database/search/spider/mediawiki_spider.py
# MediaWiki API 抓取：绕过 HTML 层反爬（实测萌娘百科 api.php 不拦截，正文可直接取）
import re
import urllib.parse

from func.log.default_log import DefaultLog

WIKIS = {
    "moegirl": ("https://mzh.moegirl.org.cn/api.php", "萌娘百科（须给准确条目名，搜索接口对匿名用户关闭）"),
}


class CatLearnMediaWikiSpider:
    """用 MediaWiki API 取条目正文 / 搜索，HTML 反爬站点也能用"""

    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

    def __init__(self, timeout=20):
        self.log = DefaultLog().getLogger()
        self.timeout = int(timeout)

    def _api(self, base, **params):
        import requests
        params.setdefault("format", "json")
        params.setdefault("formatversion", "2")
        r = requests.get(base, params=params, timeout=self.timeout,
                         headers={"User-Agent": self.UA, "Accept": "application/json"})
        r.raise_for_status()
        return r.json()

    def extract(self, title, wiki="moegirl", chars=None) -> str:
        """取条目纯文本正文（已实测萌百：200，无挑战）"""
        base, _ = WIKIS.get(wiki, WIKIS["moegirl"])
        try:
            j = self._api(base, action="query", prop="extracts", explaintext="1",
                          redirects="1", titles=title)
            pages = (j.get("query") or {}).get("pages") or []
            for p in pages:
                txt = p.get("extract") or ""
                if txt:
                    self.log.info(f"[MediaWiki] {wiki} 《{p.get('title')}》取到 {len(txt)} 字")
                    return txt if not chars else txt[:chars]
            self.log.warning(f"[MediaWiki] {wiki} 未取到正文: {title}")
        except Exception as e:
            self.log.warning(f"[MediaWiki] {wiki} 取正文异常: {type(e).__name__} {str(e)[:80]}")
        return ""

    def search(self, keyword, wiki="moegirl", limit=5):
        """Search page titles (moegirl closed list=search for anonymous users, use opensearch)"""
        base, _ = WIKIS.get(wiki, WIKIS["moegirl"])
        try:
            j = self._api(base, action="query", list="search", srsearch=keyword, srlimit=limit)
            hits = (j.get("query") or {}).get("search") or []
            return [{"title": h.get("title"), "snippet": re.sub("<[^>]+>", "", h.get("snippet") or "")}
                    for h in hits]
        except Exception as e:
            self.log.warning(f"[MediaWiki] {wiki} 搜索异常: {type(e).__name__} {str(e)[:80]}")
            return []

    def opensearch(self, keyword, wiki="moegirl", limit=5):
        """萌百找标题的备用途径（部分 wiki 允许 opensearch）"""
        base, _ = WIKIS.get(wiki, WIKIS["moegirl"])
        try:
            url = base + "?action=opensearch&search=" + urllib.parse.quote(keyword) + "&limit=%d&format=json" % limit
            import requests
            r = requests.get(url, timeout=self.timeout, headers={"User-Agent": self.UA})
            j = r.json()
            titles = (j[1] if isinstance(j, list) and len(j) > 1 else []) or []
            return titles
        except Exception as e:
            self.log.warning(f"[MediaWiki] opensearch 异常: {str(e)[:80]}")
            return []
