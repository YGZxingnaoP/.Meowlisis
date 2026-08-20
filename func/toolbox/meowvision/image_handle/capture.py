# -*- coding: utf-8 -*-
# func/toolbox/meowvision/image_handle/capture.py
# 截图工具（供父级 AI 调用）：截取全屏或指定区域，缓存图片供视觉模型使用

import os
import uuid
import datetime
from typing import Dict, List

from PIL import ImageGrab

from func.log.default_log import DefaultLog
from func.toolbox.meowvision.config import TBVisionConfig
from func.toolbox.meowvision.vision_core import TBVisionCore


class TBScreenCapture:
    """截图工具：截全屏（或指定 bbox 区域），结果缓存到 MeowVision 并返回路径"""

    TOOL_NAME = "capture_screen"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBVisionConfig()
        self.vision = TBVisionCore()

    def build_tools(self) -> List[Dict]:
        """截图工具 schema"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "截取电脑屏幕（默认全屏）。可用 bbox 指定区域 [left, top, right, bottom]；"
                    "截图后自动缓存，供视觉模型查看。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "bbox": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "可选，截图区域 [left, top, right, bottom]，缺省截全屏",
                        },
                    },
                },
            },
        }]

    def dispatch(self, name: str, arguments: Dict) -> str:
        """执行截图"""
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        arguments = arguments or {}
        bbox = arguments.get("bbox")
        return self.capture(bbox)

    def capture(self, bbox=None) -> str:
        """截屏并缓存，返回结果文本（含缓存路径）"""
        try:
            if bbox:
                bbox = tuple(int(v) for v in bbox[:4])
            img = ImageGrab.grab(bbox=bbox) if bbox else ImageGrab.grab()
            path = self._save(img)
            self.vision.add_image(path, replace=True)
            return f"截图已缓存：{path}"
        except Exception:
            self.log.exception("截图异常")
            return "错误：截图失败"

    def _save(self, img) -> str:
        """保存截图到缓存目录，返回绝对路径"""
        os.makedirs(self.config.cache_dir, exist_ok=True)
        name = f"screen_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        path = os.path.join(self.config.cache_dir, name)
        img.save(path, "PNG")
        return os.path.abspath(path)
