# -*- coding: utf-8 -*-
# func/toolbox/meowvision/image_handle/crop.py
# 图片裁切工具（供父级 AI 调用）：裁切图片区域，适用「看看屏幕右上角」等场景

import os
import re
import uuid
import datetime
from typing import Dict, List

from PIL import Image

from func.log.default_log import DefaultLog
from func.toolbox.meowvision.config import TBVisionConfig
from func.toolbox.meowvision.vision_core import TBVisionCore


class TBImageCrop:
    """图片裁切工具：按区域裁切（缓存最新图或指定图），结果缓存供视觉模型查看"""

    TOOL_NAME = "crop_image"

    REGION_ALIASES = {
        "top_left": (0.0, 0.0, 0.5, 0.5),
        "top_right": (0.5, 0.0, 1.0, 0.5),
        "bottom_left": (0.0, 0.5, 0.5, 1.0),
        "bottom_right": (0.5, 0.5, 1.0, 1.0),
        "top_half": (0.0, 0.0, 1.0, 0.5),
        "bottom_half": (0.0, 0.5, 1.0, 1.0),
        "left_half": (0.0, 0.0, 0.5, 1.0),
        "right_half": (0.5, 0.0, 1.0, 1.0),
        "center": (0.25, 0.25, 0.75, 0.75),
    }

    CN_ALIASES = {
        "左上角": "top_left", "右上角": "top_right",
        "左下角": "bottom_left", "右下角": "bottom_right",
        "上半": "top_half", "下半": "bottom_half",
        "左半": "left_half", "右半": "right_half",
        "中间": "center", "中心": "center",
    }

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBVisionConfig()
        self.vision = TBVisionCore()

    def build_tools(self) -> List[Dict]:
        """裁切工具 schema"""
        return [{
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    "裁切图片的某个区域（如用户说「看看屏幕右上角」时，裁出右上角）。"
                    "region 可用区域名 top_left/top_right/bottom_left/bottom_right/top_half/"
                    "bottom_half/left_half/right_half/center，也可用坐标 [left, top, right, bottom]。"
                    "不指定 image_path 时裁切最近一次截图/缓存的图片。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "region": {
                            "type": "string",
                            "description": "区域名或坐标，如 top_right 或 [x1,y1,x2,y2]",
                        },
                        "image_path": {
                            "type": "string",
                            "description": "可选，要裁切的图片路径；缺省用缓存的最新图",
                        },
                    },
                    "required": ["region"],
                },
            },
        }]

    def dispatch(self, name: str, arguments: Dict) -> str:
        """执行裁切"""
        if name != self.TOOL_NAME:
            return f"错误：未知工具 {name}"
        arguments = arguments or {}
        region = arguments.get("region")
        image_path = arguments.get("image_path")
        return self.crop(region, image_path)

    def crop(self, region, image_path=None) -> str:
        """裁切图片区域并缓存，返回结果文本"""
        if not region:
            return "错误：缺少裁切区域 region"

        src = image_path or self._latest_image()
        if not src or not os.path.exists(src):
            return f"错误：找不到要裁切的图片（image_path={image_path or '无缓存'}）"

        try:
            img = Image.open(src)
            w, h = img.size
            box = self._resolve_box(region, w, h)
            if box is None:
                return f"错误：无法识别的区域 {region}"
            left, top, right, bottom = box
            if right <= left or bottom <= top:
                return "错误：裁切区域无效"
            cropped = img.crop((left, top, right, bottom))
            path = self._save(cropped)
            self.vision.add_image(path, replace=True)
            return f"已裁切并缓存：{path}"
        except Exception:
            self.log.exception("图片裁切异常")
            return "错误：图片裁切失败"

    def _latest_image(self) -> str:
        images = self.vision.get_images()
        return images[-1] if images else ""

    def _resolve_box(self, region, w: int, h: int):
        if isinstance(region, (list, tuple)):
            try:
                vals = [int(v) for v in region]
                if len(vals) >= 4:
                    return vals[0], vals[1], vals[2], vals[3]
            except Exception:
                pass
            return None

        if isinstance(region, str):
            s = region.strip()
            if s in self.CN_ALIASES:
                s = self.CN_ALIASES[s]
            if s.startswith("["):
                nums = re.findall(r"-?\d+", s)
                if len(nums) >= 4:
                    return int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3])
            if s in self.REGION_ALIASES:
                l, t, r, b = self.REGION_ALIASES[s]
                return int(w * l), int(h * t), int(w * r), int(h * b)
        return None

    def _save(self, img) -> str:
        os.makedirs(self.config.cache_dir, exist_ok=True)
        name = f"crop_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        path = os.path.join(self.config.cache_dir, name)
        img.save(path, "PNG")
        return os.path.abspath(path)
