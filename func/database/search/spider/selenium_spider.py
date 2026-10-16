# -*- coding: utf-8 -*-
# func/database/search/spider/selenium_spider.py
# Selenium 辅助抓取：HTTP 被反爬拦截或返回空时，改用真实 Edge 渲染取回页面
# 驱动自动定位/自动下载：参考 D:\YOder 的 selenium_browse_tool.py 用法

import os
import re
import sys
import time
import zipfile
import subprocess
import urllib.request

from func.log.default_log import DefaultLog

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MIRROR = "https://msedgedriver.microsoft.com"


class CatLearnSeleniumSpider:
    """真实浏览器抓取（Edge + msedgedriver），无头优先，被拦时自动改用可视窗口"""

    _driver_path = ""

    def __init__(self, driver_dir: str = None, timeout: int = 25):
        self.log = DefaultLog().getLogger()
        self.timeout = int(timeout)
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        self.driver_dir = driver_dir or os.path.join(root, ".temp", "edgedriver")

    # ---------- 驱动定位 / 自动下载 ----------
    def edge_version(self) -> str:
        """读注册表拿浏览器版本"""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"SOFTWARE\Microsoft\Edge\BLBeacon") as k:
                return str(winreg.QueryValueEx(k, "version")[0])
        except Exception:
            return ""

    def _driver_version(self, path: str) -> str:
        try:
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            out = subprocess.check_output([path, "--version"], text=True,
                                          timeout=15, startupinfo=info)
            m = re.search(r"WebDriver\s+([\d.]+)", out or "")
            return m.group(1) if m else ""
        except Exception:
            return ""

    def ensure_driver(self) -> str:
        """返回可用驱动路径；版本不匹配就下载（失败则返回空串）"""
        if CatLearnSeleniumSpider._driver_path and os.path.exists(CatLearnSeleniumSpider._driver_path):
            return CatLearnSeleniumSpider._driver_path
        if os.name != "nt":
            return ""
        ver = self.edge_version()
        major = ver.split(".")[0] if ver else ""
        cands = [os.path.join(self.driver_dir, "msedgedriver.exe"),
                 os.path.join(os.getcwd(), "msedgedriver.exe")]
        for p in cands:
            if os.path.exists(p):
                dv = self._driver_version(p)
                if dv and (not major or dv.split(".")[0] == major):
                    self.log.info(f"[Selenium] 复用驱动 {p}（{dv}，浏览器 {ver}）")
                    CatLearnSeleniumSpider._driver_path = p
                    return p
                self.log.warning(f"[Selenium] 驱动版本不匹配 {p}={dv or '未知'}，浏览器={ver}，将重新下载")
        if not ver:
            return ""
        return self._download_driver(ver)

    def _download_driver(self, ver: str) -> str:
        """下载并解压与浏览器完全匹配的驱动"""
        url = f"{MIRROR}/{ver}/edgedriver_win64.zip"
        target = os.path.join(self.driver_dir, "msedgedriver.exe")
        try:
            os.makedirs(self.driver_dir, exist_ok=True)
            tmp = os.path.join(self.driver_dir, "edgedriver.zip")
            self.log.info(f"[Selenium] 下载驱动 {url}")
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                f.write(r.read())
            with zipfile.ZipFile(tmp) as z:
                for name in z.namelist():
                    if name.lower().endswith("msedgedriver.exe"):
                        with z.open(name) as s, open(target, "wb") as d:
                            d.write(s.read())
                        break
            if os.path.exists(target):
                dv = self._driver_version(target)
                self.log.info(f"[Selenium] 驱动就绪 {target}（{dv}）")
                CatLearnSeleniumSpider._driver_path = target
                return target
        except Exception as e:
            self.log.warning(f"[Selenium] 驱动下载失败 {url}: {type(e).__name__} {e}")
        return ""

    # ---------- 抓取 ----------
    def fetch(self, url: str, wait: float = 2.5, scroll: bool = False) -> str:
        """用真实浏览器取回渲染后的 HTML。

        只走无头：绝不弹可视窗口（反爬站直接返回失败，由上层决定怎么处理）。
        """
        path = self.ensure_driver()
        if not path:
            return ""
        html = self._run(path, url, wait, scroll, headless=True)
        if self._blocked(html):
            self.log.warning("[Selenium] 无头取页失败或命中反爬挑战（已禁用可视窗口回退）")
        return html

    def _blocked(self, html: str) -> bool:
        """判断拿回来的是不是反爬验证页（Cloudflare 的文案可能藏在页面很深处，要全文找）"""
        if not html:
            return True
        if len(html) < 3000:
            return True
        for kw in ("Just a moment", "Enable JavaScript and cookies",
                   "正在进行安全验证", "安全服务防护恶意自动程序",
                   "challenge-platform", "_cf_chl_opt", "cf-mitigated"):
            if kw in html:
                return True
        return False

    def _run(self, path: str, url: str, wait: float, scroll: bool, headless: bool,
             polls: int = 6) -> str:
        try:
            from selenium import webdriver
            from selenium.webdriver.edge.options import Options
            from selenium.webdriver.edge.service import Service
        except Exception as e:
            self.log.warning(f"[Selenium] 未安装 selenium: {e}")
            return ""
        o = Options()
        if headless:
            o.add_argument("--headless=new")
            o.add_argument("--blink-settings=imagesEnabled=false")
        o.add_argument("--disable-gpu")
        o.add_argument("--no-sandbox")
        o.add_argument("--disable-dev-shm-usage")
        o.add_argument("--disable-extensions")
        o.add_argument("--disable-blink-features=AutomationControlled")
        o.add_argument("--user-agent=" + USER_AGENT)
        o.add_experimental_option("excludeSwitches", ["enable-automation"])
        o.add_experimental_option("useAutomationExtension", False)
        drv = None
        try:
            drv = webdriver.Edge(service=Service(executable_path=path), options=o)
            drv.set_page_load_timeout(self.timeout)
            drv.set_script_timeout(self.timeout)
            drv.get(url)
            for _ in range(int(polls)):            # 无头 6 次(~9s) / 可视 14 次(~21s)
                time.sleep(1.5)
                src = drv.page_source or ""
                if not self._blocked(src):
                    break
            if scroll:
                try:
                    drv.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)
                except Exception:
                    pass
            return drv.page_source or ""
        except Exception as e:
            self.log.warning(f"[Selenium] 渲染失败 {url}: {type(e).__name__} {str(e)[:90]}")
            return ""
        finally:
            try:
                if drv:
                    drv.quit()
            except Exception:
                pass
