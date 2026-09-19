import os
import subprocess
import time
import urllib.request
import zipfile


USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


class DynamicBrowser:
    def __init__(self, driver_dir="./.temp/edgedriver", mirror="https://msedgedriver.microsoft.com", timeout=20):
        """动态网页渲染：无头 Edge + 自动下载驱动"""
        self.driver_dir = driver_dir
        self.mirror = str(mirror or "").rstrip("/")
        self.timeout = int(timeout)
        self._driver_path = ""

    def fetch(self, url, wait=3, scroll=False, max_length=4000):
        """用无头 Edge 渲染页面并返回正文"""
        path = self._ensure_driver()
        if not path:
            return ""
        try:
            from selenium import webdriver
            from selenium.webdriver.edge.options import Options
            from selenium.webdriver.edge.service import Service
        except Exception:
            return ""
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-extensions")
        options.add_argument("--blink-settings=imagesEnabled=false")
        options.add_argument("--user-agent=" + USER_AGENT)
        driver = None
        text = ""
        try:
            driver = webdriver.Edge(service=Service(executable_path=path), options=options)
            driver.set_page_load_timeout(self.timeout)
            driver.get(url)
            time.sleep(wait)
            if scroll:
                self._scroll(driver)
            text = driver.find_element("tag name", "body").text or ""
        except Exception:
            text = ""
        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
        if len(text) > max_length:
            text = text[:max_length] + "\n...(内容已截断)"
        return text

    def _scroll(self, driver):
        """滚动页面触发懒加载"""
        last = driver.execute_script("return document.body.scrollHeight")
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            now = driver.execute_script("return document.body.scrollHeight")
            if now == last:
                break
            last = now

    def _ensure_driver(self):
        """确保驱动可用（缓存复用或自动下载）"""
        if self._driver_path and os.path.exists(self._driver_path):
            return self._driver_path
        if os.name != "nt":
            return ""
        version = self._edge_version()
        if not version:
            return ""
        target = os.path.join(self.driver_dir, "msedgedriver.exe")
        if os.path.exists(target) and self._driver_matches(target, version):
            self._driver_path = target
            return target
        if self._download_driver(version, target):
            self._driver_path = target
            return target
        return ""

    def _edge_version(self):
        """读取注册表获取 Edge 版本"""
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Edge\BLBeacon")
            version, _ = winreg.QueryValueEx(key, "version")
            winreg.CloseKey(key)
            return str(version)
        except Exception:
            return ""

    def _driver_matches(self, path, version):
        """校验已有驱动版本是否匹配"""
        try:
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            out = subprocess.check_output([path, "--version"], text=True, timeout=10, startupinfo=info)
            return str(version).split(".")[0] in out
        except Exception:
            return False

    def _download_driver(self, version, target):
        """下载并解压 Edge 驱动"""
        url = f"{self.mirror}/{version}/edgedriver_win64.zip"
        os.makedirs(self.driver_dir, exist_ok=True)
        zip_path = os.path.join(self.driver_dir, "edgedriver.zip")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as f:
                f.write(resp.read())
            with zipfile.ZipFile(zip_path) as z:
                for name in z.namelist():
                    if name.endswith("msedgedriver.exe"):
                        with z.open(name) as src, open(target, "wb") as dst:
                            dst.write(src.read())
                        break
            return os.path.exists(target)
        except Exception:
            return False
