# -*- coding: utf-8 -*-
# func/toolbox/napcat/image/image_search.py
# 图片检测：从消息段中提取严格意义上的图片（排除表情包 / gif / 动画表情）
# 并提供图片落地到本地缓存区的能力（避免直接使用带鉴权的 url）

import os
import uuid
import urllib.request
from typing import List, Dict

from func.log.default_log import DefaultLog


class TBImageSearch:
    """图片段检测与提取：仅识别 image 段，且排除 gif / 表情；支持落地本地缓存"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    @staticmethod
    def _is_gif(data: dict) -> bool:
        """根据文件名或 subType 判断是否为 gif / 表情图"""
        if str(data.get("subType", "") or "") in ("1", 1):
            return True
        file = str(data.get("file", "") or "").lower()
        return file.endswith(".gif")

    @classmethod
    def extract_images(cls, segments) -> List[Dict]:
        """提取严格图片段信息，返回 [{url, file}]（排除 gif / 表情 / face / mface）"""
        result: List[Dict] = []
        for seg in segments or []:
            if not isinstance(seg, dict) or seg.get("type") != "image":
                continue
            data = seg.get("data") or {}
            if cls._is_gif(data):
                continue
            url = str(data.get("url", "") or "").strip()
            file = str(data.get("file", "") or "").strip()
            if url or file:
                result.append({"url": url, "file": file})
        return result

    @classmethod
    def has_image(cls, segments) -> bool:
        """判断消息段中是否包含严格图片（排除 gif / 表情）"""
        return bool(cls.extract_images(segments))

    @staticmethod
    def text_from_segments(segments) -> str:
        """提取消息段中的纯文本（供视觉决策上下文使用）"""
        buf = ""
        for seg in segments or []:
            if isinstance(seg, dict) and seg.get("type") == "text":
                buf += str((seg.get("data") or {}).get("text", "") or "")
        return buf.strip()

    # ==================== 图片落地本地缓存 ====================
    @classmethod
    def to_local_paths(cls, images: List[Dict], cache_dir: str) -> List[str]:
        """把 [{url, file}] 转成本地路径列表（优先 file，否则下载 url 到 cache_dir）。

        - file 为本地存在的路径 → 直接使用；
        - 仅有 url → 下载到 cache_dir，失败则回退 url 本身（供视觉模型自行尝试）。
        """
        result = []
        for img in images or []:
            path = cls._resolve_local(img, cache_dir)
            if path:
                result.append(path)
        return result

    @classmethod
    def _resolve_local(cls, img: Dict, cache_dir: str) -> str:
        """单个图片落地：file 优先，url 下载兜底"""
        file = str(img.get("file", "") or "").strip()
        url = str(img.get("url", "") or "").strip()

        # file 是本地存在的绝对/相对路径
        if file and os.path.exists(file):
            return os.path.abspath(file)
        # file 可能只是文件名，尝试拼 cache_dir
        if file:
            joined = os.path.join(cache_dir, os.path.basename(file))
            if os.path.exists(joined):
                return os.path.abspath(joined)

        # 下载 url 到缓存区
        if url and (url.startswith("http://") or url.startswith("https://")):
            try:
                os.makedirs(cache_dir, exist_ok=True)
                ext = cls._ext_from_url(url)
                name = f"napcat_{uuid.uuid4().hex[:12]}{ext}"
                path = os.path.join(cache_dir, name)
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp, open(path, "wb") as f:
                    f.write(resp.read())
                return os.path.abspath(path)
            except Exception:
                DefaultLog().getLogger().warning(f"NapCat 图片下载失败，回退 url: {url}")
                return url

        # 无 file、无 url：返回空
        return ""

    @staticmethod
    def _ext_from_url(url: str) -> str:
        """从 url 推断图片扩展名（缺省 .jpg）"""
        path = url.split("?")[0]
        ext = os.path.splitext(path)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
            return ext
        return ".jpg"
