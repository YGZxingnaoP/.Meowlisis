# -*- coding: utf-8 -*-
# func/database/search/spider/direct_spider.py
# 通用直连爬虫：已知详情页 URL 列表，直接抓正文（不经过搜索页）

from func.database.search.spider.base import CatLearnBaseSpider


class CatLearnDirectSpider(CatLearnBaseSpider):
    """通用直连爬虫（已知 URL 直接抓正文）

    - fetch_detail(url)：抓单个详情页正文；
    - fetch_details(urls)：批量抓多个详情页正文，返回 [{title, url, content}]。
    """

    def fetch_detail(self, url: str) -> str:
        """抓单个详情页并提取正文"""
        html = self.get(url)
        return self.extract_content(html)

    def fetch_details(self, items: list) -> list:
        """批量抓详情页正文

        items: [{title, url}, ...]
        返回: [{title, url, content}, ...]，正文为空的条目被过滤。
        """
        results = []
        for it in items or []:
            url = str(it.get("url", "") or "").strip()
            title = str(it.get("title", "") or "").strip()
            if not url:
                continue
            content = self.fetch_detail(url)
            if content:
                results.append({"title": title, "url": url, "content": content})
        return results
