# -*- coding: utf-8 -*-
"""视觉输入处理：data URL 解码、像素探测、分辨率限流、token 估算。

设计原则：本模块**不 import torch**，只用标准库 + PIL，保证 stub 阶段零重依赖。
视觉 token 估算采用 Qwen-VL 系的 patch 约定：每个 28x28 像素块约 1 个 token。
"""

from __future__ import annotations

import base64
import binascii
import io
import math
import os

_DATA_URL_PREFIX = "data:"
_PATCH_PX = 28


# ---------------------------------------------------------------- 解码
def decode_data_url(url: str) -> tuple[bytes, str]:
    """把 data URL 解成 (bytes, mime)。非 data URL 返回 (b"", "")。"""
    text = str(url or "").strip()
    if not text.startswith(_DATA_URL_PREFIX):
        return b"", ""
    try:
        header, _, payload = text.partition(",")
    except ValueError:
        return b"", ""
    if ";base64" not in header:
        return b"", ""
    mime = header[len(_DATA_URL_PREFIX):].split(";")[0] or "application/octet-stream"
    try:
        return base64.b64decode(payload, validate=False), mime
    except (binascii.Error, ValueError):
        return b"", ""


def read_local_image(path: str) -> tuple[bytes, str]:
    """读取本地图片 -> (bytes, mime)。"""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return b"", ""
    ext = os.path.splitext(path)[1].lower()
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
    }.get(ext, "application/octet-stream")
    return data, mime


# ---------------------------------------------------------------- 尺寸探测
def probe_size(data: bytes) -> tuple[int, int]:
    """只读文件头拿宽高，不解码全图。失败返回 (0, 0)。"""
    if not data:
        return 0, 0
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return (int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"))
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return (int.from_bytes(data[6:8], "little"),
                int.from_bytes(data[8:10], "little"))
    if data[:2] == b"BM" and len(data) >= 26:
        return (abs(int.from_bytes(data[18:22], "little", signed=True)),
                abs(int.from_bytes(data[22:26], "little", signed=True)))
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            w = int.from_bytes(data[24:27], "little") + 1
            h = int.from_bytes(data[27:30], "little") + 1
            return w, h
    if data[:2] == b"\xff\xd8":
        return _probe_jpeg(data)
    return 0, 0


def _probe_jpeg(data: bytes) -> tuple[int, int]:
    idx = 2
    size = len(data)
    while idx + 9 < size:
        if data[idx] != 0xFF:
            idx += 1
            continue
        marker = data[idx + 1]
        idx += 2
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if idx + 1 >= size:
            break
        seg_len = int.from_bytes(data[idx:idx + 2], "big")
        if seg_len < 2:
            break
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if idx + 7 <= size:
                height = int.from_bytes(data[idx + 3:idx + 5], "big")
                width = int.from_bytes(data[idx + 5:idx + 7], "big")
                return width, height
            break
        idx += seg_len
    return 0, 0


# ---------------------------------------------------------------- token 估算
def count_vision_tokens(width: int, height: int) -> int:
    """按 28px patch 估算视觉 token 数。"""
    if width <= 0 or height <= 0:
        return 0
    return max(1, math.ceil(width / _PATCH_PX) * math.ceil(height / _PATCH_PX))


# ---------------------------------------------------------------- 限流
def cap_pixels(data: bytes, max_pixels: int, min_pixels: int = 0) -> tuple[bytes, str]:
    """把图片压到 [min_pixels, max_pixels] 之间。返回 (bytes, note)。

    仅当超限或不足时才重新编码；无 PIL 或解码失败时原样返回。
    """
    if not data:
        return data, ""
    width, height = probe_size(data)
    if width <= 0 or height <= 0:
        return data, ""
    pixels = width * height
    if max_pixels and pixels <= max_pixels and (not min_pixels or pixels >= min_pixels):
        return data, ""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return data, "PIL 不可用，未缩放"
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = img.convert("RGB")
            scale = 1.0
            if max_pixels and pixels > max_pixels:
                scale = math.sqrt(max_pixels / pixels)
            elif min_pixels and pixels < min_pixels:
                scale = math.sqrt(min_pixels / pixels)
            new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
            if new_size == (width, height):
                return data, ""
            resized = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="JPEG", quality=88)
            note = f"{width}x{height} -> {new_size[0]}x{new_size[1]}"
            return buf.getvalue(), note
    except Exception:  # noqa: BLE001
        return data, ""


# ---------------------------------------------------------------- messages
def collect_images(messages: list[dict]) -> list[dict]:
    """从 messages 里抽出所有 image_url 块，返回 [{url, source}]。"""
    found: list[dict] = []
    for msg in messages or []:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            if isinstance(image_url, dict):
                url = image_url.get("url") or ""
            else:
                url = str(image_url or "")
            if url:
                found.append({"url": url})
    return found


def summarize_images(messages: list[dict], max_pixels: int,
                     min_pixels: int = 0, cap: bool = True) -> dict:
    """统计一次请求里的图像信息，供 meta 与限流使用。"""
    images = collect_images(messages)
    total_pixels = 0
    total_tokens = 0
    details = []
    for item in images:
        data, mime = decode_data_url(item["url"])
        if not data:
            details.append({"mime": "url", "note": "非 data URL，未统计"})
            continue
        if cap:
            data, note = cap_pixels(data, max_pixels, min_pixels)
        else:
            note = ""
        width, height = probe_size(data)
        tokens = count_vision_tokens(width, height)
        total_pixels += width * height
        total_tokens += tokens
        details.append({"mime": mime, "width": width, "height": height,
                        "tokens": tokens, "note": note})
    return {
        "count": len(images),
        "pixels": total_pixels,
        "tokens": total_tokens,
        "details": details,
    }
