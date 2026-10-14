# -*- coding: utf-8 -*-
# func/database/search/spider/base.py
# 通用爬虫基类：HTTP 请求（SSRF 防护/重试/限速）+ 正文提取

import io
import json
import io
import json
import os
import time
import socket
import ipaddress
from urllib.parse import urlparse

from func.log.default_log import DefaultLog


class CatLearnBaseSpider:
    """通用爬虫基类

    - 统一请求头、超时、重试、限速；
    - SSRF 防护（仅公网 http/https）；
    - 正文提取（trafilatura 优先，lxml 回退）。
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    def __init__(self, interval: float = 1.5, timeout: float = 20):
        self.log = DefaultLog().getLogger()
        self.interval = interval
        self.timeout = timeout
        self._last_request = 0.0

    # ==================== 请求 ====================
    def _respect_limit(self):
        """同站限速：距离上次请求不足 interval 则等待"""
        wait = self.interval - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def get(self, url: str, params: dict = None) -> str:
        """GET 请求返回文本（HTML/纯文本），失败返回空串"""
        if not self.is_safe_url(url):
            self.log.warning(f"非法或内网地址，拒绝访问: {url}")
            return ""
        self._respect_limit()
        import requests
        last_err = None
        hdrs = dict(self.HEADERS)
        hdrs.update(self._session_headers(url))
        for attempt in range(2):
            try:
                resp = requests.get(url, params=params, headers=hdrs,
                                    cookies=self._session_cookies(url),
                                    timeout=self.timeout, allow_redirects=True)
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding
                text = resp.text
                # Cloudflare 托管挑战：403 + "Just a moment..." / "Enable JavaScript and cookies"
                if resp.headers.get('cf-mitigated') == 'challenge' or (
                        'Just a moment...' in text[:2000]
                        or 'Enable JavaScript and cookies to continue' in text[:4000]):
                    self.log.warning(f'被反爬挑战拦截（Cloudflare），改用真实浏览器: {url}')
                    return self._selenium_get(url, params)
                return text
            except Exception as e:
                last_err = e
                if attempt == 0:
                    time.sleep(1)
        status = getattr(getattr(last_err, 'response', None), 'status_code', 0)
        if status in (403, 429, 503) or last_err is None:
            self.log.warning(f"GET 失败 {url}: {last_err} → 改用真实浏览器")
            return self._selenium_get(url, params)
        self.log.warning(f"GET 失败 {url}: {last_err}")
        return ""

    def get_json(self, url: str, params: dict = None) -> dict:
        """GET 请求返回 JSON dict，失败返回空 dict"""
        if not self.is_safe_url(url):
            return {}
        self._respect_limit()
        import requests
        try:
            resp = requests.get(url, params=params, headers=self.HEADERS,
                                timeout=self.timeout, allow_redirects=True)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.log.warning(f"GET JSON 失败 {url}: {e}")
            return {}

    # ============ 人工验证会话（一次验证，长期复用） ============
    SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))), '.temp', 'web_sessions.json')

    @classmethod
    def _load_sessions(cls) -> dict:
        try:
            return json.loads(io.open(cls.SESSION_FILE, encoding='utf-8').read())
        except Exception:
            return {}

    def _host_key(self, url: str) -> str:
        try:
            from urllib.parse import urlparse
            return (urlparse(url).hostname or '').lower()
        except Exception:
            return ''

    def _session_cookies(self, url: str) -> dict:
        """带上该站点已验证会话的 cookie（人工过一次验证后保存）"""
        s = self._load_sessions().get(self._host_key(url)) or {}
        out = {}
        for n, v in (s.get('cookies') or {}).items():
            out[n] = v
        if out:
            self.log.info(f"[会话] 复用 {self._host_key(url)} 的 {len(out)} 个 cookie")
        return out

    def _session_headers(self, url: str) -> dict:
        s = self._load_sessions().get(self._host_key(url)) or {}
        return {'User-Agent': s.get('ua')} if s.get('ua') else {}

    def _selenium_get(self, url: str, params: dict = None) -> str:
        """HTTP 被反爬拦下时的兜底：用真实 Edge 渲染取回页面"""
        if params:
            try:
                from urllib.parse import urlencode
                if '?' not in url:
                    url = url + '?' + urlencode(params)
            except Exception:
                pass
        try:
            from func.database.search.spider.selenium_spider import CatLearnSeleniumSpider
            sp = getattr(self, '_sel', None)
            if sp is None:
                sp = CatLearnSeleniumSpider()
                self._sel = sp
            html = sp.fetch(url)
            if html:
                self.log.info(f"[Selenium] 成功取回 {url}（{len(html)} 字节）")
            else:
                self.log.warning(f"[Selenium] 仍未取回内容 {url}")
            return html or ""
        except Exception as e:
            self.log.warning(f"[Selenium] 兜底异常: {type(e).__name__} {str(e)[:90]}")
            return ""

    # ==================== 正文提取 ====================
    def extract_content(self, html: str) -> str:
        """从 HTML 提取正文（trafilatura 优先，lxml 回退）"""
        if not html:
            return ""
        try:
            import trafilatura
            text = trafilatura.extract(html, include_comments=False, include_tables=True)
            if text:
                return text.strip()
        except Exception:
            pass
        return self._extract_body_text(html)

    def _extract_body_text(self, html: str) -> str:
        """lxml 提取 body 文本（trafilatura 失败回退）"""
        try:
            from lxml import html as lhtml
            doc = lhtml.fromstring(html)
            for bad in doc.xpath("//script | //style | //noscript"):
                bad.getparent().remove(bad)
            text = doc.text_content()
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            return "\n".join(lines)
        except Exception:
            return ""

    # ==================== SSRF 防护 ====================
    @staticmethod
    def is_safe_url(url: str) -> bool:
        """仅允许 http/https 公网地址"""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname
        if not host:
            return False
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        for info in infos:
            ip_str = info[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast):
                return False
        return True
