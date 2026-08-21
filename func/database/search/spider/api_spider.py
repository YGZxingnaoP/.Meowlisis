# -*- coding: utf-8 -*-
# func/database/search/spider/api_spider.py
# 通用 API 爬虫：请求 JSON 接口，按字段路径提取结果列表

from func.database.search.spider.base import CatLearnBaseSpider


class CatLearnApiSpider(CatLearnBaseSpider):
    """通用 API 爬虫（JSON 接口）

    - fetch_search(url, params)：请求接口返回 JSON dict；
    - parse_results(data, rules)：按字段路径提取 [{title, url}]。
    """

    def fetch_search(self, url: str, params: dict = None) -> dict:
        """请求 JSON 接口，返回 dict"""
        return self.get_json(url, params)

    def parse_results(self, data: dict, rules: dict) -> list:
        """按字段路径提取结果列表 [{title, url}]

        rules 结构：
        {
            "list_path": "query.search",      # 结果列表所在字段路径
            "title_key": "title",             # 标题字段名
            "url_key": "url",                 # URL 字段名（可选）
            "url_prefix": "https://..."       # URL 前缀（可选，拼相对路径）
        }
        """
        if not data or not rules:
            return []
        try:
            items = data
            list_path = rules.get("list_path", "")
            if list_path:
                for key in list_path.split("."):
                    if isinstance(items, dict):
                        items = items.get(key)
                    else:
                        items = None
                    if items is None:
                        break
            if not isinstance(items, list):
                return []
            results = []
            title_key = rules.get("title_key", "title")
            url_key = rules.get("url_key", "url")
            prefix = rules.get("url_prefix", "")
            for it in items:
                if not isinstance(it, dict):
                    continue
                title = str(it.get(title_key, "") or "").strip()
                url = str(it.get(url_key, "") or "").strip()
                if url and prefix and not url.startswith("http"):
                    url = prefix.rstrip("/") + "/" + url.lstrip("/")
                if title and url:
                    results.append({"title": title, "url": url})
            return results
        except Exception as e:
            self.log.warning(f"API 解析结果失败: {e}")
            return []
