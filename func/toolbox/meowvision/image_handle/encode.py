# -*- coding: utf-8 -*-
# func/toolbox/meowvision/image_handle/encode.py
# 图片编码工具（供父级 AI 调用）：将本地图片编码为 base64 data url

import base64
import os
import uuid
import datetime
from typing import Dict, List

from func.log.default_log import DefaultLog
from func.toolbox.meowvision.config import TBVisionConfig
from func.toolbox.meowvision.vision_core import TBVisionCore


class TBImageEncode:
    """图片编码工具：把本地图片编码为 base64 data url，完整内容落盘并缓存"""

    TOOL_NAME = "encode_image"

    MIME = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBVisionConfig()
        self.vision = TBVisionCore()

    def build_tools(self) -> List[Dict]:
        """编码工具 schema"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "把本地图片编码为 base64 data url。完整结果保存为文本文件，"
                    "并缓存该 data url 供视觉模型使用。不指定 image_path 时编码最近缓存的图片。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_path": {
                            "type": "string",
                            "description": "可选，要编码的本地图片路径；缺省用缓存的最新图",
                        },
                    },
                },
            },
        }]

    def dispatch(self, name: str, arguments: Dict) -> str:
        """执行编码"""
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        arguments = arguments or {}
        return self.encode(arguments.get("image_path"))

    def encode(self, image_path=None) -> str:
        """编码图片为 base64 data url，返回结果文本"""
        src = image_path or self._latest_image()
        if not src or not os.path.exists(src):
            return f"错误：找不到要编码的图片（image_path={image_path or '无缓存'}）"

        try:
            ext = os.path.splitext(src)[1].lower()
            mime = self.MIME.get(ext, "application/octet-stream")
            with open(src, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            data_url = f"data:{mime};base64,{b64}"

            # 完整 data url 落盘，避免超长文本污染 AI 上下文
            os.makedirs(self.config.cache_dir, exist_ok=True)
            name = f"encode_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.txt"
            txt_path = os.path.join(self.config.cache_dir, name)
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(data_url)

            # 缓存 data url（视觉模型可直接识别）
            self.vision.add_image(data_url, replace=False)

            preview = data_url[:80]
            return f"编码完成，长度 {len(data_url)}，完整内容：{txt_path}，预览：{preview}..."
        except Exception:
            self.log.exception("图片编码异常")
            return "错误：图片编码失败"

    def _latest_image(self) -> str:
        images = self.vision.get_images()
        return images[-1] if images else ""
