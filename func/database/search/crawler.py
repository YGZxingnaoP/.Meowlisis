# -*- coding: utf-8 -*-
# func/database/search/crawler.py
# 搜索爬取组件：站点规则 + 通用爬虫（http/api/mediawiki/direct），供 Agent 的
# search_site / visit_url 调用；批次落盘由 search_core 负责。

import re
import os
import json
import time
import uuid
from urllib.parse import quote

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.database.config import CatLearnConfig
from func.database.search.spider.http_spider import CatLearnHttpSpider
from func.database.search.spider.api_spider import CatLearnApiSpider
from func.database.search.spider.direct_spider import CatLearnDirectSpider


@singleton
class CatLearnCrawler:
    """搜索爬取组件（单例）

    - 站点解析规则（SITE_RULES）+ 通用爬虫；
    - 只提供 search_site（搜索）与 fetch_url（取正文）两个能力，供 Agent 调用；
    - 批次落盘由 search_core 负责，本类不写 content.txt。
    """

    # mediawiki 站点正文上限（api.php 是全文接口，取太多会撑爆分块与上下文）
    MEDIAWIKI_CHARS = 3000

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
            "search_url": "https://so.3dmgame.com/?keyword={q}&subsearch=1&type=1",
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
        """抓取单个 URL 正文（供 Agent 的 visit_url / collect_selected 调用）

        - mediawiki 站点（萌娘百科）：HTML 详情页被 Cloudflare 拦成 403 挑战页，
          改走 api.php 取正文（唯一可用路径）；
        - site 配置了 detail_xpath：定向提取（如 3dm 只取游戏详情卡）；
        - 否则走默认 trafilatura/lxml 正文提取。
        """
        rule = self.SITE_RULES.get(site) if site else None

        if rule and str(rule.get("spider") or "") == "mediawiki":
            title = self._wiki_title_of(url)
            wiki = rule.get("wiki") or site
            if title and wiki:
                txt = self._mediawiki_extract(title, wiki)
                if txt:
                    return txt
            self.log.warning(f"[MediaWiki] 未能取到正文，放弃该 URL: {url}")
            return ""

        if rule and rule.get("detail_xpath"):
            txt = self._fetch_detail_by_xpath(url, rule["detail_xpath"])
            if txt:
                return txt
            # 定向 xpath 会随站点改版失效；此时回落通用正文提取，避免静默丢内容
            self.log.warning(f"定向提取为空，回落通用提取: {url}")
        return self.direct_spider.fetch_detail(url)

    # ==================== MediaWiki（HTML 反爬站点的唯一可用路径） ====================
    @staticmethod
    def _wiki_title_of(url: str) -> str:
        """从 MediaWiki 条目 URL 反解条目名

        兼容两种形式：
        - https://host/<条目名>（已 URL 编码）
        - https://host/index.php?title=<条目名>
        搜索页 / 首页返回空串（不是条目页）。
        """
        try:
            from urllib.parse import urlparse, unquote, parse_qs
            p = urlparse(url)
            qs = parse_qs(p.query or "")
            if qs.get("title"):
                return str(qs["title"][0]).strip()
            if qs.get("search") or not p.path or p.path in ("/", "/index.php", "/api.php"):
                return ""
            return unquote(p.path.rstrip("/").rsplit("/", 1)[-1]).strip()
        except Exception:
            return ""

    def _mediawiki_extract(self, title: str, wiki: str) -> str:
        """用 MediaWiki api.php 取条目正文（不抓 HTML，不会遇到 403 挑战页）"""
        try:
            from func.database.search.spider.mediawiki_spider import CatLearnMediaWikiSpider
            if getattr(self, "_mw_spider", None) is None:
                self._mw_spider = CatLearnMediaWikiSpider()
            return self._mw_spider.extract(title, wiki, chars=self.MEDIAWIKI_CHARS) or ""
        except Exception:
            self.log.exception(f"[MediaWiki] 取正文异常: {wiki}/{title}")
            return ""

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

        # selenium 策略：真实浏览器渲染（反爬站用）
        if strategy == "selenium":
            html = self._selenium_search(search_url)
            if not html:
                self.log.warning(f"[搜索] selenium 策略未取回内容: {search_url}")
                return []
            parse_rule = dict(rule.get("parse") or {})
            parse_rule.setdefault("base_url", rule.get("base_url", site_cfg.get("base_url", "")))
            if parse_rule.get("slug"):
                return self._parse_gamesgg(html, rule)
            return self._dedup(self.http_spider.parse_results(html, parse_rule))
        # mediawiki 策略：走 MediaWiki API（HTML 被反爬，api.php 开放）
        if strategy == "mediawiki":
            return self._mediawiki_search(site, search_keys, rule, site_cfg)


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
    def _mediawiki_search(self, site: str, keyword: str, rule: dict, site_cfg: dict) -> list:
        """mediawiki 策略：opensearch 找标题 → api.php 取正文（HTML 反爬也能用）"""
        try:
            from func.database.search.spider.mediawiki_spider import CatLearnMediaWikiSpider
            if getattr(self, "_mw_spider", None) is None:
                self._mw_spider = CatLearnMediaWikiSpider()
            mw = self._mw_spider
            wiki = rule.get("wiki") or site
            limit = int(rule.get("limit") or 3)
            base_url = (rule.get("base_url") or site_cfg.get("base_url") or "").rstrip("/")
            titles = mw.opensearch(keyword, wiki, limit)
            if not titles:
                titles = [h.get("title") for h in mw.search(keyword, wiki, limit)]
            out = []
            for t in (titles or [])[:limit]:
                if not t:
                    continue
                txt = self._mediawiki_extract(t, wiki)
                if not txt:
                    continue
                out.append({"title": t, "url": base_url + "/" + quote(t),
                            "snippet": re.sub(r"\s+", " ", txt)[:300], "content": txt})
            self.log.info(f"[搜索] mediawiki {wiki} 关键词《{keyword}》命中 {len(out)} 条")
            return self._dedup(out)
        except Exception as e:
            self.log.warning(f"[搜索] mediawiki 异常: {type(e).__name__} {str(e)[:80]}")
            return []


    def _selenium_search(self, url: str) -> str:
        """用真实浏览器取搜索页（spider=selenium 策略）"""
        try:
            from func.database.search.spider.selenium_spider import CatLearnSeleniumSpider
            if getattr(self, '_sel_spider', None) is None:
                self._sel_spider = CatLearnSeleniumSpider()
            return self._sel_spider.fetch(url) or ""
        except Exception as e:
            self.log.warning(f"[搜索] selenium 取页异常: {type(e).__name__} {str(e)[:80]}")
            return ""

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

CatLearnCrawler.SITE_RULES.update({
    "moegirl": {"name": "萌娘百科", "base_url": "https://mzh.moegirl.org.cn",
                "spider": "mediawiki", "wiki": "moegirl", "limit": 3},
})
