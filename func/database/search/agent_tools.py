# -*- coding: utf-8 -*-
# func/database/search/agent_tools.py
# 搜索 Agent 工具：search_site / visit_url / select_result

import json
from urllib.parse import urlparse

from func.log.default_log import DefaultLog
from func.database.config import CatLearnConfig


class CatLearnAgentTools:
    """搜索 Agent 工具集（供 CatLearnAgent 多轮循环调用）

    三个工具：
    - search_site(site, query)：用单个精准词搜索站点，返回结果列表；
    - visit_url(url)：访问详情页，返回正文（同站点白名单约束）；
    - select_result(url, reason)：AI 决定保留某 URL 为最终结果。

    AI 不产出总结文字，只做"搜索 → 看正文 → 挑选结果"的决策；
    最终落盘的是 AI 选中结果的原文，而非改写内容。
    """

    TOOL_SEARCH = "search_site"
    TOOL_VISIT = "visit_url"
    TOOL_SELECT = "select_result"

    def __init__(self, crawler=None):
        self.log = DefaultLog().getLogger()
        self.config = CatLearnConfig()
        self.crawler = crawler
        # 本轮已 search_site 返回过的 URL 集合（visit_url 白名单来源）
        self._known_urls = set()
        # URL -> title 映射（search_site 时记录，供选中结果回填标题）
        self._url_titles = {}
        # 已选中的结果 [{title, url, reason}]
        self.selected = []
        # 当前 task 所属站点（用于详情页定向提取）
        self.current_site = ""

    def set_crawler(self, crawler):
        self.crawler = crawler

    def set_site(self, site: str):
        self.current_site = site or ""

    def reset(self):
        """每轮 task 开始前重置状态"""
        self._known_urls = set()
        self._url_titles = {}
        self.selected = []
        self.current_site = ""

    # ==================== 工具 schema ====================
    def build_tools(self) -> list:
        site_keys = self.config.site_keys()
        return [
            {
                "type": "function",
                "function": {
                    "name": self.TOOL_SEARCH,
                    "description": (
                        "在指定站点用【单个精准词】搜索，返回结果列表（标题+URL）。"
                        "用于找到与当前搜索主题最相关的结果页面。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "site": {
                                "type": "string",
                                "enum": site_keys,
                                "description": "站点标识",
                            },
                            "query": {
                                "type": "string",
                                "description": "单个精准搜索词（专有名词/名称优先）",
                            },
                        },
                        "required": ["site", "query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": self.TOOL_VISIT,
                    "description": (
                        "访问某个搜索结果页面的 URL，提取正文文本。"
                        "用于判断该页面内容是否准确、是否值得保留为最终结果。"
                        "只能访问 search_site 返回过的 URL（或同站点域名下的页面）。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "完整网址（来自 search_site 返回结果）",
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": self.TOOL_SELECT,
                    "description": (
                        "决定保留某个 URL 的正文作为最终搜索结果。"
                        "可以多次调用，每次选择一个有价值的结果。"
                        "价值标准（必须与搜索词强相关）："
                        "定义/详情（百科词条、游戏详情、产品介绍）> 强相关评价（评测/攻略）"
                        "> 强相关近期新闻；丢弃广告、无关、弱相关内容。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "要保留的结果 URL",
                            },
                            "reason": {
                                "type": "string",
                                "description": "一句话说明为何保留（如：这是游戏详情页，信息最准确）",
                            },
                        },
                        "required": ["url", "reason"],
                    },
                },
            },
        ]

    # ==================== 工具执行 ====================
    def execute(self, name: str, arguments: dict) -> str:
        """执行单个工具，返回字符串结果（回传给 LLM）"""
        try:
            if name == self.TOOL_SEARCH:
                return self._do_search(arguments)
            if name == self.TOOL_VISIT:
                return self._do_visit(arguments)
            if name == self.TOOL_SELECT:
                return self._do_select(arguments)
            return f"错误：未知工具 {name}"
        except Exception as e:
            self.log.exception(f"Agent 工具 {name} 执行异常")
            return f"工具执行失败：{e}"

    def _do_search(self, args: dict) -> str:
        site = str(args.get("site", "") or "").strip()
        query = str(args.get("query", "") or "").strip()
        if not site or not query:
            return "错误：缺少 site 或 query 参数"
        if self.crawler is None:
            return "错误：搜索爬虫未初始化"

        results = self.crawler.search_site(site, query)
        # 记录已知 URL 与标题，供 visit_url 白名单校验与结果回填
        for r in results or []:
            url = str(r.get("url", "") or "").strip()
            title = str(r.get("title", "") or "").strip()
            if url:
                self._known_urls.add(url)
                if title and url not in self._url_titles:
                    self._url_titles[url] = title

        if not results:
            return "（未搜索到结果）"
        # 只返回标题和 URL，不把正文塞进上下文
        lines = [f"{i + 1}. {r.get('title', '')} -> {r.get('url', '')}" for i, r in enumerate(results)]
        return "\n".join(lines)

    def _do_visit(self, args: dict) -> str:
        url = str(args.get("url", "") or "").strip()
        if not url:
            return "错误：缺少 url 参数"
        if not self._url_allowed(url):
            return "错误：该 URL 不在允许访问范围（须来自 search_site 返回结果或同站点域名）"
        if self.crawler is None:
            return "错误：搜索爬虫未初始化"

        content = self.crawler.fetch_url(url, self.current_site)
        if not content or not content.strip():
            return "（该页面未能提取到正文）"
        max_chars = self.config.agent_visit_max_chars
        if len(content) > max_chars:
            content = content[:max_chars] + "\n...[内容过长已截断]"
        return content

    def _do_select(self, args: dict) -> str:
        url = str(args.get("url", "") or "").strip()
        reason = str(args.get("reason", "") or "").strip()
        if not url:
            return "错误：缺少 url 参数"
        if not self._url_allowed(url):
            return "错误：该 URL 不在允许访问范围"

        # 去重，避免同一 URL 被重复选择
        for item in self.selected:
            if item.get("url") == url:
                return f"（已选择过 {url}，跳过重复）"
        self.selected.append({"url": url, "reason": reason})
        return f"已选择：{url}（{reason}）"

    # ==================== 白名单校验 ====================
    def _url_allowed(self, url: str) -> bool:
        """只允许访问 search_site 返回过的 URL，或已见 URL 的同站点域名"""
        # 已明确返回过的 URL 直接放行
        if url in self._known_urls:
            return True
        # 同站点域名校验
        try:
            target = urlparse(url)
            if target.scheme not in ("http", "https") or not target.hostname:
                return False
            for known in self._known_urls:
                kp = urlparse(known)
                if kp.hostname and kp.hostname == target.hostname:
                    return True
        except Exception:
            return False
        return False

    # ==================== 结果收集 ====================
    def collect_selected(self, fetch_content=True) -> list:
        """把选中的结果补全标题与正文，返回 [{title, url, reason, content}]"""
        out = []
        for item in self.selected:
            url = item.get("url", "")
            content = ""
            title = ""
            if fetch_content and self.crawler is not None:
                content = self.crawler.fetch_url(url, self.current_site) or ""
            # 尝试从已知搜索结果里找回标题
            title = self._title_of(url)
            out.append({
                "title": title,
                "url": url,
                "reason": item.get("reason", ""),
                "content": content,
            })
        return out

    def _title_of(self, url: str) -> str:
        """从 search_site 记录里找回标题"""
        return self._url_titles.get(url, "")
