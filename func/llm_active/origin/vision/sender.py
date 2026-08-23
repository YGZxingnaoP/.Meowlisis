# -*- coding: utf-8 -*-
# func/llm_active/origin/vision/sender.py
# 主动回复视觉发送层：多张图片 + 文本提示词 → 视觉模型

import base64
import os
from typing import List, Optional

from func.log.default_log import DefaultLog
from func.llm_active.origin.vision.config import AutoVisionConfig
from func.llm_active.origin.vision.port.aliyun import AutoVisionAliyunLLM


class AutoVisionSender:
    """构建视觉消息并调用视觉模型，返回模型原始回复（未做正则清理）"""

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
        self.config = AutoVisionConfig()
        self.llm = AutoVisionAliyunLLM(self.config)

    def send(self, images: List[str], text_prompt: str = "",
             system_prompt: str = "") -> Optional[str]:
        """发送多张图片 + 文本提示词给视觉模型，返回模型回复（content），失败返回 None"""
        if not images:
            self.log.warning("主动回复视觉发送失败：无图片")
            return None
        if not self.llm.client:
            self.log.error("主动回复视觉客户端不可用")
            return None

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        content = []
        for img in images:
            url = self._to_url(img)
            if url:
                content.append({"type": "image_url", "image_url": {"url": url}})
        if not content:
            self.log.warning("主动回复视觉发送失败：图片无法编码")
            return None
        content.append({"type": "text", "text": (text_prompt or "请看看这些图片")})
        messages.append({"role": "user", "content": content})

        return self.llm.chat(messages)

    @classmethod
    def _to_url(cls, img) -> str:
        """将图片输入规范为视觉模型可用的 url：http/data 直通，本地路径转 base64 data url"""
        if not img:
            return ""
        s = str(img).strip()
        if s.startswith("http://") or s.startswith("https://") or s.startswith("data:"):
            return s
        if os.path.exists(s):
            try:
                ext = os.path.splitext(s)[1].lower()
                mime = cls.MIME.get(ext, "application/octet-stream")
                with open(s, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                return f"data:{mime};base64,{b64}"
            except Exception:
                return ""
        return ""
