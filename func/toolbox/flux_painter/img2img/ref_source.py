# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/img2img/ref_source.py
# 参考图素材：消息图片落地成本地缓存 + 本地图片转 data url
# 文件读取与缓存都留在绘画模块内部，不再走 pipeline 桥接。

import base64
import os
import urllib.request
import uuid

from PIL import Image

from func.log.default_log import DefaultLog


IMAGE_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".bmp": "image/bmp",
}

MAX_BYTES = 20 * 1024 * 1024      # 参考图下载上限（超过就丢弃，避免把内存/磁盘打满）
MAX_SIDE = 2048                   # 参考图长边上限（再大对出图没意义，只会拖慢上传/编码）


def image_data_url(path: str) -> str:
    """本地图片 → data url（供多模态消息使用，按扩展名给 MIME）"""
    mime = IMAGE_MIME.get(os.path.splitext(str(path))[1].lower(), "image/png")
    try:
        with open(path, "rb") as f:
            return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""


class TBRefSource:
    """参考图落地：消息里的 file / url → 本地文件，统一放进参考图缓存目录"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def materialize(self, images, cache_dir: str) -> str:
        """返回第一张可用参考图的本地路径；取不到返回空串"""
        paths = self.materialize_all(images, cache_dir)
        return paths[0] if paths else ""

    def materialize_all(self, images, cache_dir: str) -> list:
        """把消息图片逐张落地并归一化，只返回确实可用的本地 PNG"""
        out = []
        for item in (images or []):
            path = self._resolve(item, cache_dir)
            if not path:
                continue
            path = self.normalize(path, cache_dir)
            if path:
                out.append(path)
        return out

    def normalize(self, path: str, cache_dir: str) -> str:
        """任意格式 → 静态 PNG：动图只取第一帧、透明垫白、长边限幅

        ComfyUI 的 LoadImage 与多模态模型对 gif/动图/超大图都不稳，
        统一在这里退化成一张干净的 RGB PNG，后面的取景/上传/看图都只认它。
        """
        try:
            with Image.open(path) as im:
                im.seek(0)                                  # 动图取第一帧
                rgba = im.convert("RGBA")
                canvas = Image.new("RGB", rgba.size, (255, 255, 255))
                canvas.paste(rgba, mask=rgba.split()[-1])   # 透明部分垫白
                side = max(canvas.size)
                if side > MAX_SIDE:
                    ratio = MAX_SIDE / float(side)
                    canvas = canvas.resize(
                        (max(1, int(canvas.width * ratio)), max(1, int(canvas.height * ratio))),
                        Image.LANCZOS)
                os.makedirs(cache_dir, exist_ok=True)
                dst = os.path.join(cache_dir, f"ref_{uuid.uuid4().hex[:12]}.png")
                canvas.save(dst, "PNG")
                return os.path.abspath(dst)
        except Exception:
            self.log.warning(f"[flux_painter] 参考图归一化失败，原样使用: {os.path.basename(path)}")
            return path if os.path.isfile(path) else ""

    def _resolve(self, image, cache_dir: str) -> str:
        """单张图片落地：先认本地路径，再按文件名找缓存，最后才下载 url"""
        if not isinstance(image, dict):
            return ""
        file = str(image.get("file") or "").strip()
        if file and os.path.isfile(file):
            return os.path.abspath(file)
        if file:
            joined = os.path.join(cache_dir, os.path.basename(file))
            if os.path.isfile(joined):
                return os.path.abspath(joined)
        url = str(image.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            return ""
        try:
            os.makedirs(cache_dir, exist_ok=True)
            path = os.path.join(cache_dir, f"ref_{uuid.uuid4().hex[:12]}{self._ext(url)}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(path, "wb") as f:
                got = 0
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > MAX_BYTES:          # 超大图直接放弃，避免把内存/磁盘打满
                        f.close()
                        os.remove(path)
                        self.log.warning(f"[flux_painter] 参考图超过 {MAX_BYTES // 1048576}MB，已丢弃")
                        return ""
                    f.write(chunk)
            return os.path.abspath(path)
        except Exception:
            self.log.warning(f"[flux_painter] 参考图下载失败: {url[:80]}")
            return ""

    @staticmethod
    def _ext(url: str) -> str:
        """从 url 推断扩展名（不认识的按 png）"""
        path = url.split("?")[0]
        ext = os.path.splitext(path)[1].lower()
        return ext if ext in IMAGE_MIME else ".png"
