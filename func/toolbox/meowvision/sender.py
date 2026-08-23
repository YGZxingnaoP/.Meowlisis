# -*- coding: utf-8 -*-
# func/toolbox/meowvision/sender.py
# MeowVision 发送层：发送一张或多张图片 + 用户消息 + 角色提示词给视觉模型

import base64
import os
from typing import List, Optional

from func.log.default_log import DefaultLog
from func.toolbox.meowvision.config import TBVisionConfig
from func.toolbox.meowvision.port.aliyun import TBVisionAliyunLLM


class TBVisionSender:
    """构建视觉消息并调用视觉理解模型，返回模型原始回复（未做正则清理）"""

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
        self.llm = TBVisionAliyunLLM(self.config)

    def send(self, images: List[str], user_message: str = "",
             system_prompt: str = "", history_messages: Optional[List[dict]] = None,
             tools: Optional[List[dict]] = None, tool_choice=None):
        """发送图片与文本给视觉模型，返回完整响应对象（含 content 与 tool_calls），失败返回 None

        - history_messages：短期记忆上下文（[{role, content}]），插入到最终图片消息之前。
        - tools / tool_choice：透传给视觉模型，支持 function calling。
        """
        if not images:
            self.log.warning("MeowVision 发送失败：无图片")
            return None
        if not self.llm.client:
            self.log.error("MeowVision 视觉客户端不可用")
            return None

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 短期记忆上下文（纯文本，放在图片消息之前）
        for m in history_messages or []:
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": str(m["content"])})

        content = []
        for img in images:
            url = self._to_url(img)
            if url:
                content.append({"type": "image_url", "image_url": {"url": url}})
        if not content:
            self.log.warning("MeowVision 发送失败：图片无法编码")
            return None
        content.append({"type": "text", "text": (user_message or "请看看这张图片")})
        messages.append({"role": "user", "content": content})

        return self.llm.chat(messages, tools=tools, tool_choice=tool_choice)

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
