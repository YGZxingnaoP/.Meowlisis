# -*- coding: utf-8 -*-
# func/toolbox/napcat/image/image_search.py
# 图片检测：从消息段中提取严格意义上的图片（排除表情包 subType=1，保留 gif 动图后续抽帧）
# 并提供图片落地到本地缓存区的能力（避免直接使用带鉴权的 url）

import os
import re
import uuid
import urllib.request
from typing import List, Dict

from func.log.default_log import DefaultLog


class TBImageSearch:
    """图片段检测与提取：识别 image 段，排除表情包；支持落地本地缓存与动图抽帧"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    @staticmethod
    def _is_emoji(data: dict) -> bool:
        """subType=1 表示 QQ 表情/动画表情，不作为图片内容处理"""
        return str(data.get("subType", "") or "") in ("1", 1)

    @classmethod
    def extract_images(cls, segments) -> List[Dict]:
        """提取图片段信息，返回 [{url, file}]（排除表情 subType=1；gif 动图保留，后续抽帧）"""
        result: List[Dict] = []
        for seg in segments or []:
            if not isinstance(seg, dict) or seg.get("type") != "image":
                continue
            data = seg.get("data") or {}
            if cls._is_emoji(data):
                continue
            url = str(data.get("url", "") or "").strip()
            file = str(data.get("file", "") or "").strip()
            if url or file:
                result.append({"url": url, "file": file})
        return result

    # markdown 图片：![...](url)
    IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

    @classmethod
    def extract_markdown_images(cls, segments) -> List[Dict]:
        """从 markdown 段提取图片链接 [{url, file}]，供本地落地（幻梦等机器人发图走 markdown）"""
        result: List[Dict] = []
        for seg in segments or []:
            if not isinstance(seg, dict) or seg.get("type") != "markdown":
                continue
            content = str((seg.get("data") or {}).get("content", "") or "")
            for m in cls.IMG_RE.findall(content):
                url = m.strip()
                if url.startswith(("http://", "https://")):
                    result.append({"url": url, "file": ""})
        return result

    @classmethod
    def has_image(cls, segments) -> bool:
        """判断消息段中是否包含图片（排除表情包 subType=1）"""
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
    def prepare_for_vision(cls, images: List[Dict], cache_dir: str) -> List[str]:
        """落地图片 → 限制张数 → 超限压缩 → 动图抽帧，返回最终交给视觉模块的路径列表。

        处理顺序：
        1. 落地本地（file 优先，url 下载）；
        2. 最多保留最近 max_images 张（超限取最后 N 张）；
        3. 静态图超 max_image_size_mb 则压缩；动图先抽帧再对帧压缩；
        4. 动图（GIF）→ 抽中间帧±偏移两帧做相似度比对，达标取前者，否则取两帧。
        """
        from func.toolbox.napcat.image.gif_frame import TBGifFrame
        paths = cls.to_local_paths(images, cache_dir)

        # 最多 N 张，超限取最近（最后）的 N 张
        max_n = cls._max_images()
        if max_n and max_n > 0 and len(paths) > max_n:
            paths = paths[-max_n:]

        final: List[str] = []
        for p in paths:
            if not p:
                continue
            if not os.path.exists(p):
                # 落地失败回退的 url，原样交给视觉模型
                final.append(p)
                continue
            if TBGifFrame.is_animated(p):
                # 动图：先抽帧，再逐帧压缩
                for frame in TBGifFrame().select_frames(p, cache_dir):
                    final.append(cls._compress_if_needed(frame, cache_dir))
            else:
                final.append(cls._compress_if_needed(p, cache_dir))
        return final

    @classmethod
    def prepare_static_only(cls, images: List[Dict], cache_dir: str) -> List[str]:
        # 落地图片后只保留静态图（跳过动图），再压缩返回
        from func.toolbox.napcat.image.gif_frame import TBGifFrame
        paths = cls.to_local_paths(images, cache_dir)

        max_n = cls._max_images()
        if max_n and max_n > 0 and len(paths) > max_n:
            paths = paths[-max_n:]

        final: List[str] = []
        for p in paths:
            if not p:
                continue
            if not os.path.exists(p):
                final.append(p)
                continue
            if TBGifFrame.is_animated(p):
                continue
            final.append(cls._compress_if_needed(p, cache_dir))
        return final

    @staticmethod
    def gather_text_context(current_text: str, history_messages: List[dict],
                            limit: int = 3) -> str:
        """向上检索文本：当前无文本时，从历史（text-only OpenAI messages）取最近用户文本作上下文。

        - current_text 非空则直接返回；
        - 否则先过滤出全部 user 文本，再取最近 limit 条，逗号合并返回（仍为空则返回空串）。
        """
        current = (current_text or "").strip()
        if current:
            return current
        user_texts = []
        for m in history_messages or []:
            if isinstance(m, dict) and m.get("role") == "user":
                content = str(m.get("content") or "").strip()
                if content:
                    user_texts.append(content)
        return "，".join(user_texts[-limit:])

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

    # ==================== 张数 / 大小限制 ====================
    @staticmethod
    def _max_images() -> int:
        """单次最多处理图片数（配置 max_images，默认 5；<=0 表示不限制）"""
        try:
            from func.toolbox.napcat.config import TBNapCatConfig
            return int(TBNapCatConfig().max_images)
        except Exception:
            return 5

    @staticmethod
    def _max_image_bytes() -> int:
        """单张图片大小上限（字节，配置 max_image_size_mb，默认 2MB）"""
        try:
            from func.toolbox.napcat.config import TBNapCatConfig
            mb = float(TBNapCatConfig().max_image_size_mb)
            return int(mb * 1024 * 1024)
        except Exception:
            return 2 * 1024 * 1024

    @classmethod
    def _compress_if_needed(cls, path: str, cache_dir: str) -> str:
        """图片超过大小上限时压缩（逐步缩尺寸 + 降质量重存为 JPEG），未超限原样返回。

        - 压缩失败回退原图；
        - 压缩后仍可能略超上限（极端情况），但已尽量逼近上限。
        """
        max_bytes = cls._max_image_bytes()
        try:
            if os.path.getsize(path) <= max_bytes:
                return os.path.abspath(path)
        except OSError:
            return path

        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            os.makedirs(cache_dir, exist_ok=True)
            out = os.path.join(cache_dir, f"napcat_cmp_{uuid.uuid4().hex[:10]}.jpg")

            # 逐级缩小最长边，并逐步降质量，直到 <= max_bytes
            for max_dim in (4096, 3072, 2304, 1728, 1296, 972, 729, 547):
                w, h = img.size
                if max(w, h) > max_dim:
                    ratio = max_dim / max(w, h)
                    resized = img.resize(
                        (max(1, int(w * ratio)), max(1, int(h * ratio))),
                        Image.LANCZOS,
                    )
                else:
                    resized = img
                for quality in (85, 75, 60):
                    resized.save(out, "JPEG", quality=quality, optimize=True)
                    try:
                        if os.path.getsize(out) <= max_bytes:
                            return os.path.abspath(out)
                    except OSError:
                        continue
            return os.path.abspath(out)
        except Exception:
            DefaultLog().getLogger().warning(f"图片压缩失败，使用原图: {path}")
            return path
