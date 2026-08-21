# -*- coding: utf-8 -*-
# func/database/search/spider/http_spider.py
# 通用 HTTP 爬虫：抓取搜索结果页 HTML，按站点规则解析结果列表，再抓详情页正文

from func.database.search.spider.base import CatLearnBaseSpider


class CatLearnHttpSpider(CatLearnBaseSpider):
    """通用 HTTP 爬虫（HTML）

    - fetch_search(url)：抓搜索结果页 HTML；
    - parse_results(html, rules)：按传入规则从 HTML 提取 [{title, url}]；
    - fetch_detail(url)：抓详情页并提取正文。
    """

    def fetch_search(self, url: str) -> str:
        """抓搜索结果页 HTML，返回原始 HTML（供解析）"""
        return self.get(url)

    def parse_results(self, html: str, rules: dict) -> list:
        """按规则从搜索结果页提取结果列表 [{title, url}]

        rules 结构（由站点适配层提供）：
        {
            "item_xpath": "//div[contains(@class,'result')]",   # 结果条目
            "title_xpath": ".//a/text()",                        # 标题（相对 item）
            "link_xpath": ".//a/@href",                          # 链接（相对 item）
        }
        也支持 json 型站点（rules 含 json_path 时走 json 解析）。
        """
        if not html or not rules:
            return []
        item_xpath = rules.get("item_xpath")
        if item_xpath:
            return self._parse_by_xpath(html, rules)
        json_path = rules.get("json_path")
        if json_path:
            return self._parse_by_json(html, rules)
        return []

    def fetch_detail(self, url: str) -> str:
        """抓详情页并提取正文"""
        html = self.get(url)
        return self.extract_content(html)

    # ==================== 解析实现 ====================
    def _parse_by_xpath(self, html: str, rules: dict) -> list:
        try:
            from lxml import html as lhtml
            from urllib.parse import urljoin
            doc = lhtml.fromstring(html)
            items = doc.xpath(rules.get("item_xpath", ""))
            results = []
            for item in items:
                title = self._first_text(item, rules.get("title_xpath", ""))
                link = self._first_attr(item, rules.get("link_xpath", ""))
                if link:
                    link = urljoin(rules.get("base_url", ""), link)
                if title and link:
                    results.append({"title": title, "url": link})
            return results
        except Exception as e:
            self.log.warning(f"xpath 解析结果失败: {e}")
            return []

    def _parse_by_json(self, html: str, rules: dict) -> list:
        """从页面内嵌 __NEXT_DATA__ 等 JSON 解析结果（供 SPA/SSG 站点）"""
        try:
            import json
            import re
            json_path = rules.get("json_path", "")
            m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            if not m:
                return []
            data = json.loads(m.group(1))
            for key in json_path.split("."):
                if isinstance(data, dict):
                    data = data.get(key)
                else:
                    data = None
                if data is None:
                    break
            results = []
            if isinstance(data, list):
                for it in data:
                    if not isinstance(it, dict):
                        continue
                    title = it.get("title") or it.get("name") or ""
                    url = it.get("url") or it.get("link") or it.get("href") or ""
                    if title and url:
                        results.append({"title": str(title), "url": str(url)})
            return results
        except Exception as e:
            self.log.warning(f"json 解析结果失败: {e}")
            return []

    @staticmethod
    def _first_text(item, xpath: str) -> str:
        if not xpath:
            return ""
        try:
            nodes = item.xpath(xpath)
            if nodes:
                first = nodes[0]
                if isinstance(first, str):
                    return first.strip()
                return (first.text_content() or "").strip()
        except Exception:
            pass
        return ""

    @staticmethod
    def _first_attr(item, xpath: str) -> str:
        if not xpath:
            return ""
        try:
            nodes = item.xpath(xpath)
            if nodes:
                return str(nodes[0]).strip()
        except Exception:
            pass
        return ""
