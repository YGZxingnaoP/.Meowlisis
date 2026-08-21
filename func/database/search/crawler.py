# -*- coding: utf-8 -*-
# func/database/search/crawler.py
# 搜索爬取编排：站点规则 + 通用爬虫（http/api/direct），同站队列、异站并行，缓存到 web_result

import os
import json
import time
import uuid
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.config import CatLearnConfig
from func.database.search.spider.http_spider import CatLearnHttpSpider
from func.database.search.spider.api_spider import CatLearnApiSpider
from func.database.search.spider.direct_spider import CatLearnDirectSpider


@singleton
class CatLearnCrawler:
    """搜索爬虫（单例）

    - 站点解析规则（SITE_RULES）+ 三个通用爬虫；
    - 相同站点串行（队列），不同站点并行；
    - 每站爬取条数单独配置（默认 5）；
    - 结果缓存 .temp/database/web_result/{batch_id}/{task_id}/（meta.json + content.txt）。
    """

    # 站点解析规则：搜索 URL 模板 + 结果列表解析规则
    SITE_RULES = {
        "mcmod": {
            "spider": "http",
            "search_url": "https://search.mcmod.cn/s?key={q}",
            "parse": {
                "item_xpath": "//a[contains(@href,'/class/') and not(contains(@href,'/category/'))]",
                "title_xpath": ".",
                "link_xpath": "@href",
            },
            "base_url": "https://www.mcmod.cn",
        },
        "moegirl": {
            "spider": "http",
            "search_url": "https://mzh.moegirl.org.cn/index.php?search={q}&fulltext=1",
            "parse": {
                "item_xpath": "//div[contains(@class,'mw-search-result-heading')]",
                "title_xpath": ".//a[1]/@title",
                "link_xpath": ".//a[1]/@href",
            },
            "base_url": "https://mzh.moegirl.org.cn",
        },
        "3dmgame": {
            "spider": "http",
            "search_url": "https://so.3dmgame.com/?keyword={q}",
            "parse": {
                "item_xpath": "//a[@class='bt']",
                "title_xpath": ".",
                "link_xpath": "@href",
            },
            "base_url": "https://www.3dmgame.com",
            # 游戏详情页定向提取：只取右侧游戏信息卡（类型/开发/平台/评分/简介），
            # 跳过左侧新闻 feed 与页脚导航，避免新闻污染知识库。
            "detail_xpath": "//div[contains(@class,'Rlist6')]",
        },
        "baidu": {
            "spider": "http",
            "search_url": "https://www.baidu.com/s?wd={q}",
            "parse": {
                "item_xpath": "//h3/a",
                "title_xpath": ".",
                "link_xpath": "@href",
            },
            "base_url": "https://www.baidu.com",
        },
    }

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = CatLearnConfig()
        self.http_spider = CatLearnHttpSpider()
        self.api_spider = CatLearnApiSpider()
        self.direct_spider = CatLearnDirectSpider()

    @property
    def web_result_dir(self) -> str:
        return os.path.join(".temp", "database", "web_result")

    # ==================== 编排入口 ====================
    def crawl(self, batch_id: str, tasks: list):
        """按站点分组：同站串行、异站并行，爬取结果落盘 web_result/{batch_id}/"""
        if not batch_id or not tasks:
            return
        groups = {}
        for t in tasks:
            site = str(t.get("web_url", "") or "")
            groups.setdefault(site, []).append(t)

        with ThreadPoolExecutor(max_workers=max(1, len(groups))) as pool:
            futures = {
                pool.submit(self._crawl_group, batch_id, site, group): site
                for site, group in groups.items()
            }
            for fut in as_completed(futures):
                site = futures[fut]
                try:
                    fut.result()
                except Exception:
                    self.log.exception(f"站点 {site} 爬取组异常")

    def _crawl_group(self, batch_id: str, site: str, tasks: list):
        """同站串行队列：逐条爬取"""
        for task in tasks:
            try:
                self._crawl_task(batch_id, site, task)
            except Exception:
                self.log.exception(f"爬取任务失败: site={site} task={task}")
            # 同站限速
            time.sleep(1.5)

    def _crawl_task(self, batch_id: str, site: str, task: dict):
        """单个任务：搜索 → 解析结果列表 → 抓前 N 条详情正文 → 合并落盘"""
        site_cfg = self.config.site_config(site)
        rule = self.SITE_RULES.get(site) or {}
        strategy = str(site_cfg.get("strategy", "") or rule.get("spider", "http") or "http")
        count = int(site_cfg.get("count", 5) or 5)
        search_keys = str(task.get("search_keys", "") or "")

        # 1. 抓搜索结果 → 解析结果列表
        results = self._search(site, search_keys, strategy, rule, site_cfg)
        results = results[:count]

        # 2. 抓详情页正文（direct 爬虫，同站串行已由外层保证）
        details = []
        for item in results:
            try:
                content = self.direct_spider.fetch_detail(item["url"])
                if content:
                    details.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "content": content,
                    })
            except Exception:
                self.log.exception(f"抓详情失败: {item.get('url')}")
            time.sleep(0.8)

        # 3. 合并落盘
        merged = "\n\n".join([
            f"【{d.get('title','')}】\n{d.get('content','')}" for d in details
        ])
        task_id = str(task.get("task_id", "0"))
        task_dir = os.path.join(self.web_result_dir, str(batch_id), task_id)
        os.makedirs(task_dir, exist_ok=True)

        meta = {
            "task_id": task.get("task_id"),
            "search_keys": search_keys,
            "site": site,
            "strategy": strategy,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": [{"title": d["title"], "url": d["url"]} for d in details],
        }
        with open(os.path.join(task_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        with open(os.path.join(task_dir, "content.txt"), "w", encoding="utf-8") as f:
            f.write(merged or "")

    # ==================== 搜索 + 解析 ====================
    def search_site(self, site: str, query: str) -> list:
        """公开方法：用单个精准词搜索站点，返回结果列表 [{title, url}]（供 agent 调用）"""
        rule = self.SITE_RULES.get(site)
        if not rule:
            return []
        site_cfg = self.config.site_config(site)
        strategy = str(site_cfg.get("strategy", "") or rule.get("spider", "http") or "http")
        return self._search(site, query, strategy, rule, site_cfg)

    def fetch_url(self, url: str, site: str = None) -> str:
        """公开方法：抓取单个 URL 正文（供 agent 调用）

        - site 配置了 detail_xpath 时，走定向提取（如 3dm 只取游戏详情卡）；
        - 否则走默认 trafilatura/lxml 正文提取。
        """
        if site:
            rule = self.SITE_RULES.get(site)
            if rule and rule.get("detail_xpath"):
                return self._fetch_detail_by_xpath(url, rule["detail_xpath"])
        return self.direct_spider.fetch_detail(url)

    def _fetch_detail_by_xpath(self, url: str, xpath: str) -> str:
        """按 xpath 定向提取详情页正文（过滤导航/新闻/页脚）"""
        html = self.direct_spider.get(url)
        if not html:
            return ""
        try:
            from lxml import html as lhtml
            doc = lhtml.fromstring(html)
            parts = []
            for node in doc.xpath(xpath):
                text = (node.text_content() or "").strip()
                if text:
                    # 压缩多余空白行
                    lines = [l.strip() for l in text.splitlines() if l.strip()]
                    parts.append("\n".join(lines))
            return "\n".join(parts)
        except Exception:
            self.log.exception(f"定向提取详情失败: {url}")
            return ""

    def _search(self, site: str, search_keys: str, strategy: str,
                rule: dict, site_cfg: dict) -> list:
        """按站点规则搜索并解析结果列表 [{title, url}]"""
        search_url = self._search_url(site, search_keys, rule, site_cfg)

        if strategy == "api":
            data = self.api_spider.fetch_search(search_url)
            parse_rule = rule.get("parse", {}) or {}
            return self.api_spider.parse_results(data, parse_rule)

        # http 默认
        html = self.http_spider.fetch_search(search_url)
        if not html:
            return []
        parse_rule = rule.get("parse", {}) or {}
        parse_rule = dict(parse_rule)
        parse_rule.setdefault("base_url", rule.get("base_url", site_cfg.get("base_url", "")))

        if parse_rule.get("slug"):
            return self._parse_gamesgg(html, rule)
        results = self.http_spider.parse_results(html, parse_rule)
        return self._dedup(results)

    def _parse_gamesgg(self, html: str, rule: dict) -> list:
        """games.gg 游戏详情页 /{slug}/ 形式，从 slug 推断标题"""
        import re
        base = rule.get("base_url", "https://games.gg")
        # 排除导航/功能页 slug
        nav = {"games", "guides", "reviews", "news", "games-plus", "about",
               "contact", "privacy", "terms", "login", "signup", "search",
               "quests", "mystery-box", "lists", "deals", "esports",
               "tier-lists", "redeem-codes", "rewards", "profile", "settings"}
        seen = set()
        results = []
        for m in re.finditer(r'href="/([a-z0-9][a-z0-9-]+)/"', html):
            slug = m.group(1)
            if slug in nav or slug in seen:
                continue
            seen.add(slug)
            title = slug.replace("-", " ").title()
            results.append({"title": title, "url": f"{base.rstrip('/')}/{slug}/"})
        return results

    @staticmethod
    def _dedup(results: list) -> list:
        """按 url 去重，保留首次出现"""
        seen = set()
        out = []
        for r in results or []:
            url = r.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(r)
        return out

    def _search_url(self, site: str, search_keys: str, rule: dict, site_cfg: dict) -> str:
        """构造搜索 URL：config search_url > 内置模板 > base_url"""
        template = site_cfg.get("search_url") or rule.get("search_url") or ""
        q = quote(search_keys.strip())
        if template:
            return template.replace("{q}", q)
        base = site_cfg.get("base_url", "") or rule.get("base_url", "")
        if base:
            return f"{base.rstrip('/')}/?q={q}"
        return f"https://www.baidu.com/s?wd={q}"

    # ==================== 批次落盘辅助 ====================
    def write_batch_meta(self, batch_id: str, trigger: str, username: str, tasks: list):
        """写入批次 meta.json（在爬取前调用，供 learning 读取）"""
        task_dir = os.path.join(self.web_result_dir, str(batch_id))
        os.makedirs(task_dir, exist_ok=True)
        meta = {
            "batch_id": batch_id,
            "trigger": trigger,
            "username": username,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "task_count": len(tasks or []),
        }
        with open(os.path.join(task_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    @staticmethod
    def new_batch_id() -> str:
        return f"{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    # ==================== 站点验证（供前端验证脚本/接口复用） ====================
    def verify_site(self, site_key: str, test_query: str = "测试") -> dict:
        """验证站点是否可爬取，返回 {ok, message, sample}"""
        rule = self.SITE_RULES.get(site_key)
        if not rule:
            return {"ok": False, "message": f"未知站点标识: {site_key}", "sample": []}
        site_cfg = self.config.site_config(site_key)
        strategy = str(site_cfg.get("strategy", "") or rule.get("spider", "http") or "http")
        try:
            results = self._search(site_key, test_query, strategy, rule, site_cfg)
            if not results:
                return {"ok": False, "message": "未解析到结果（可能反爬或关键词无结果）", "sample": []}
            return {
                "ok": True,
                "message": f"成功解析 {len(results)} 条结果",
                "sample": results[:5],
            }
        except Exception as e:
            return {"ok": False, "message": f"验证异常: {e}", "sample": []}
