import re
from itertools import zip_longest

import requests
from html import unescape


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


class WebSearch:
    def __init__(self, config, browser=None):
        """内置搜索：百度+必应协同，支持翻页与动态页"""
        self.config = config
        self.browser = browser

    def search(self, query, page=1):
        """搜索第 page 页，返回结果列表"""
        query = (query or "").strip()
        if not query:
            return []
        page = max(1, int(page or 1))
        engine = getattr(self.config, "engine", "both")
        baidu, bing = [], []
        if engine in ("both", "baidu"):
            baidu = self._safe(self._baidu, query, page)
        if engine in ("both", "bing"):
            bing = self._safe(self._bing, query, page)
        if engine == "baidu":
            return baidu[:self.config.top_n]
        if engine == "bing":
            return bing[:self.config.top_n]
        return self._merge(baidu, bing, self.config.top_n)

    def open(self, url, dynamic=False):
        """打开网页取正文"""
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            return "无效链接"
        try:
            html = self._get(url)
        except Exception:
            html = ""
        text = self._extract(html) if html else ""
        if self._useful(text):
            return self._trim(text)
        use_dynamic = bool(dynamic) or getattr(self.config, "dynamic", "auto") == "auto"
        if use_dynamic and self.browser:
            dynamic_text = self.browser.fetch(url, max_length=self.config.page_chars)
            if self._useful(dynamic_text):
                return dynamic_text
        return "内容无效或需要脚本渲染，建议换一条结果或翻页获取更多线索。"

    def _safe(self, func, query, page):
        """安全执行搜索"""
        try:
            return func(query, page)
        except Exception:
            return []

    def _baidu(self, query, page):
        """百度搜索解析"""
        html = self._get("https://www.baidu.com/s",
                         params={"wd": query, "pn": str((page - 1) * 10), "rn": "10", "ie": "utf-8"})
        results = []
        for block in re.split(r'<div[^>]+class="result[^"]*"', html)[1:]:
            m = re.search(r'<h3[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
            if not m:
                continue
            title = self._strip(m.group(2))
            if not title:
                continue
            snippet = ""
            for pat in (r'class="c-abstract"[^>]*>(.*?)</div>',
                        r'class="[^"]*content-right[^"]*"[^>]*>(.*?)</div>',
                        r'class="c-span-last"[^>]*>(.*?)</div>'):
                sm = re.search(pat, block, re.S)
                if sm:
                    snippet = self._strip(sm.group(1))
                    break
            results.append({"title": title, "url": m.group(1), "snippet": snippet})
        return results

    def _bing(self, query, page):
        """必应搜索解析"""
        html = self._get("https://cn.bing.com/search",
                         params={"q": query, "first": str((page - 1) * 10 + 1), "setlang": "zh-Hans"})
        results = []
        for block in re.split(r'<li\s[^>]*\bclass="[^"]*\bb_algo\b[^"]*"[^>]*>', html)[1:]:
            m = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.S)
            if not m:
                continue
            a = re.search(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', m.group(1), re.S)
            if not a:
                continue
            title = self._strip(a.group(2))
            if not title:
                continue
            snippet = ""
            sm = re.search(r'<p[^>]*class="[^"]*b_lineclamp\d?[^"]*"[^>]*>(.*?)</p>', block, re.S)
            if sm:
                snippet = self._strip(sm.group(1))
            results.append({"title": title, "url": a.group(1), "snippet": snippet})
        return results

    def _merge(self, first, second, top_n):
        """合并去重并混排两组结果"""
        seen, merged = set(), []
        for pair in zip_longest(first, second):
            for item in pair:
                if not item:
                    continue
                key = item.get("url") or item.get("title")
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= top_n:
                    return merged
        return merged

    def _get(self, url, params=None):
        """发起 HTTP 请求"""
        headers = {"User-Agent": UA,
                   "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                   "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
        resp = requests.get(url, params=params, headers=headers, timeout=self.config.timeout, allow_redirects=True)
        resp.raise_for_status()
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = "utf-8"
        return resp.text

    def _extract(self, html):
        """提取网页正文"""
        try:
            import trafilatura
            text = trafilatura.extract(html, include_comments=False, include_tables=True,
                                       include_images=False, include_links=False)
            if text:
                return text
        except Exception:
            pass
        return self._strip_simple(html)

    @staticmethod
    def _useful(text):
        """判断正文是否有效"""
        if not text or len(text) < 200:
            return False
        low = text.lower()
        for marker in ("enable javascript", "requires javascript", "启用javascript", "需要开启"):
            if marker in low:
                return False
        return True

    def _trim(self, text):
        """截断过长正文"""
        if len(text) > self.config.page_chars:
            return text[:self.config.page_chars] + "\n...(内容已截断)"
        return text

    @staticmethod
    def _strip(text):
        """去除标签与实体"""
        text = re.sub(r"<[^>]+>", " ", text or "")
        return re.sub(r"\s+", " ", unescape(text)).strip()

    def _strip_simple(self, html):
        """简单清洗 HTML 取纯文本"""
        html = re.sub(r"<script[^>]*>.*?</script>", " ", html or "", flags=re.S | re.I)
        html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.S | re.I)
        html = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", unescape(html))).strip()
