# -*- coding: utf-8 -*-
"""网络搜图：百度图片（JSON 接口）+ 必应图片（HTML 兜底）。

* 只取能落地、尺寸达标、能通过 Pillow 校验的图；全部下载到 assets/ 并记录来源
* 来源信息（页面标题 + 图片直链）由调用方汇总进文末「图片来源」清单
* 搜索/下载失败一律返回空，不打断出稿
"""

import hashlib
import html as _html
import os
import re
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

MIN_W = 700
MIN_H = 450
MAX_BYTES = 8 * 1024 * 1024


class ImageSearch:
    def __init__(self, config):
        """网络搜图（复用 docwriter 的 search 配置：超时/引擎）"""
        self.timeout = int(getattr(config, "timeout", 15) or 15)
        self.engine = str(getattr(config, "engine", "both") or "both")
        self.min_w = int(getattr(config, "image_min_w", MIN_W) or MIN_W)
        self.min_h = int(getattr(config, "image_min_h", MIN_H) or MIN_H)
        self.max_side = int(getattr(config, "image_max_side", 1600) or 1600)
        self.last_error = ""

    # ==================== 搜索 ====================
    def search(self, query, n=10):
        """搜图，返回候选列表 [{url,title,w,h,engine}]"""
        q = str(query or "").strip()
        if not q:
            return []
        items = []
        if self.engine in ("both", "baidu"):
            items += self._safe(self._baidu, q, n)
        if len(items) < n and self.engine in ("both", "bing"):
            items += self._safe(self._bing, q, n)
        out, seen = [], set()
        for it in items:
            url = it.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(it)
            if len(out) >= n:
                break
        return out

    def _safe(self, fn, *args):
        try:
            return fn(*args)
        except Exception as e:
            self.last_error = str(e)[:160]
            return []

    def _baidu(self, query, n):
        """百度图片 JSON 接口（无需 key，国内可直连）"""
        params = {
            "tn": "resultjson_com", "ipn": "rj", "ct": "201326592", "is": "", "fp": "result",
            "word": query, "queryWord": query, "cl": "2", "lm": "-1", "ie": "utf-8",
            "oe": "utf-8", "st": "-1", "z": "", "ic": "0", "hd": "", "latest": "",
            "copyright": "", "s": "", "se": "", "tab": "", "width": "", "height": "",
            "face": "0", "istype": "2", "qc": "", "nc": "1", "expermode": "", "nojc": "",
            "isAsync": "", "pn": "0", "rn": str(max(n * 3, 30)), "gsm": "1e",
        }
        resp = requests.get("https://image.baidu.com/search/acjson", params=params,
                            headers={"User-Agent": UA, "Referer": "https://image.baidu.com/",
                                     "Accept": "application/json, text/plain, */*"},
                            timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json().get("data") or []
        out = []
        for it in data:
            if not isinstance(it, dict):
                continue
            url = it.get("hoverURL") or it.get("middleURL") or it.get("thumbURL") or ""
            for ru in (it.get("replaceUrl") or []):
                if isinstance(ru, dict) and ru.get("ObjURL"):
                    url = ru["ObjURL"]
                    break
            if not url:
                continue
            out.append({"url": url,
                        "title": _strip(it.get("fromPageTitleEnc") or it.get("fromPageTitle") or ""),
                        "w": int(it.get("width") or 0), "h": int(it.get("height") or 0),
                        "engine": "baidu"})
        return out

    def _bing(self, query, n):
        """必应图片异步接口，从 HTML 里抓 murl"""
        url = "https://cn.bing.com/images/async"
        resp = requests.get(url, params={"q": query, "first": "1",
                                        "count": str(max(n * 3, 30)), "mmasync": "1"},
                            headers={"User-Agent": UA, "Referer": "https://cn.bing.com/images/"},
                            timeout=self.timeout)
        resp.raise_for_status()
        text = resp.text
        out = []
        for m in re.finditer(r'murl&quot;:&quot;(.*?)&quot;', text):
            src = _html.unescape(m.group(1))
            if src.startswith("http"):
                out.append({"url": src, "title": "", "w": 0, "h": 0, "engine": "bing"})
        if not out:
            for m in re.finditer(r'"murl":"(.*?)"', text):
                src = _html.unescape(m.group(1))
                if src.startswith("http"):
                    out.append({"url": src, "title": "", "w": 0, "h": 0, "engine": "bing"})
        return out

    # ==================== 下载 ====================
    def download(self, url, out_dir, referer="https://image.baidu.com/", prefix="web"):
        """下载并校验一张图，返回 {path,source,w,h} 或 None"""
        from PIL import Image

        url = str(url or "").strip()
        if not url.startswith(("http://", "https://")):
            return None
        try:
            resp = requests.get(url, headers={"User-Agent": UA, "Referer": referer},
                                timeout=self.timeout, stream=True)
            resp.raise_for_status()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if ctype and not ctype.startswith("image"):
                return None
            raw = resp.content
        except Exception as e:
            self.last_error = f"下载失败：{e}"
            return None
        if not raw or len(raw) > MAX_BYTES:
            return None
        os.makedirs(out_dir, exist_ok=True)
        tmp = os.path.join(out_dir, f".tmp_{int(time.time() * 1000)}")
        try:
            with open(tmp, "wb") as f:
                f.write(raw)
            with Image.open(tmp) as im:
                fmt = (im.format or "").upper()
                w, h = im.size
                if fmt not in ("JPEG", "PNG", "WEBP", "BMP", "GIF"):
                    raise ValueError(f"格式不支持 {fmt}")
                if w < self.min_w or h < self.min_h:
                    raise ValueError(f"尺寸过小 {w}x{h}")
                rgb = im.convert("RGB")
                if rgb.width > self.max_side:               # 压到合理尺寸，避免成品文件过大
                    ratio = self.max_side / float(rgb.width)
                    rgb = rgb.resize((self.max_side, max(1, int(rgb.height * ratio))),
                                     Image.LANCZOS)
                w, h = rgb.width, rgb.height                # 落盘后的实际尺寸
                tag = hashlib.md5(raw).hexdigest()[:8]
                path = os.path.join(out_dir, f"{prefix}_{tag}.jpg")
                if not os.path.isfile(path):
                    rgb.save(path, "JPEG", quality=88)
        except Exception as e:
            self.last_error = str(e)[:160]
            try:
                os.remove(tmp)
            except Exception:
                pass
            return None
        finally:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except Exception:
                pass
        return {"path": path, "source": url, "w": w, "h": h}

    def fetch(self, query, out_dir, n=1, referer="https://image.baidu.com/"):
        """搜 + 下，返回最多 n 张达标图片 [{path,source,w,h,title}]"""
        got, seen = [], set()
        for cand in self.search(query, max(n * 4, 8)):
            if len(got) >= n:
                break
            info = self.download(cand["url"], out_dir, referer=referer,
                                 prefix="web")
            if not info or info["path"] in seen:
                continue
            seen.add(info["path"])
            info["title"] = cand.get("title") or query
            info["engine"] = cand.get("engine") or ""
            got.append(info)
        return got


def _strip(text):
    """去标签/实体"""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html.unescape(str(text or "")))).strip()


def build_source_list(items):
    """把下载记录汇总成文末「图片来源」清单（Markdown 列表）"""
    lines = []
    for i, it in enumerate(items or [], 1):
        title = str(it.get("title") or "网络图片").strip()[:60]
        src = str(it.get("source") or "")
        lines.append(f"{i}. {title}（{it.get('w', '?')}×{it.get('h', '?')}） 来源：{src}")
    return lines
