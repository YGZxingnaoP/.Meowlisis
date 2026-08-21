# -*- coding: utf-8 -*-
# func/toolbox/meowvision/get_response.py
# MeowVision 响应层：获取视觉模型回复（图片描述 + 角色回复），并做正则优化

import re
from typing import List, Dict, Optional

from func.log.default_log import DefaultLog
from func.toolbox.meowvision.get_prompt import TBVisionGetPrompt
from func.toolbox.meowvision.sender import TBVisionSender


class TBVisionGetResponse:
    """获取视觉模型回复：发送图片与消息，返回 {description, reply}。

    - description：图片基本描述（50~80字纯文本），仅用于记忆，不参与 TTS / 发送。
    - reply：以角色身份对图片的正式回复，用于 TTS / 发送 / 记忆。
    - need_description=False（角色自己截图）时，不要求输出描述，description 恒为空串。
    """

    # 分析性引导词（命中则截断，与主链路 Output.remove_analysis 完全一致）
    ANALYSIS_KEYWORDS = ["这段对话", "这段文字", "这个对话"]

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.get_prompt = TBVisionGetPrompt()
        self.sender = TBVisionSender()

    def analyze(self, images: List[str], user_message: str = "",
                username: str = "", need_description: bool = True,
                history_messages: Optional[List[dict]] = None) -> Dict[str, str]:
        """返回 {"description": str, "reply": str}"""
        system_prompt = self.get_prompt.get_system_prompt(
            username, user_message, need_description=need_description
        )
        raw = self.sender.send(images, user_message, system_prompt, history_messages)
        return self._split(raw, need_description)

    # ==================== 解析 ====================
    @classmethod
    def _split(cls, raw, need_description: bool) -> Dict[str, str]:
        """把模型输出拆成 description 与 reply（严格按【图片描述】/【回复】标记）"""
        if not raw:
            return {"description": "", "reply": ""}
        text = str(raw)

        # 先剥离 think 标签（qvq 思考内容）
        text = cls._strip_think(text)

        if not need_description:
            return {"description": "", "reply": cls.clean(text)}

        desc_marker = "【图片描述】"
        reply_marker = "【回复】"
        desc = ""
        reply = ""

        desc_idx = text.find(desc_marker)
        reply_idx = text.find(reply_marker)

        if desc_idx != -1 and reply_idx != -1 and reply_idx > desc_idx:
            desc = text[desc_idx + len(desc_marker): reply_idx]
            reply = text[reply_idx + len(reply_marker):]
        elif desc_idx != -1:
            # 只有描述标记，没有回复标记：全部作为描述兜底，回复为空
            desc = text[desc_idx + len(desc_marker):]
        else:
            # 没有标记：全部作为回复（兜底）
            reply = text

        return {
            "description": cls._normalize_desc(desc),
            "reply": cls.clean(reply),
        }

    @staticmethod
    def _strip_think(text: str) -> str:
        """移除 <think>...</think> 及未闭合 think 标签"""
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
        return text

    @classmethod
    def _normalize_desc(cls, desc: str) -> str:
        """图片描述：纯文本、去 markdown、限制长度（50~80字目标，超长截断到100字）"""
        text = (desc or "").strip()
        if not text:
            return ""
        # 去 markdown 加粗/链接/图片
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = text.replace("**", "").replace("`", "")
        # 去换行与多余空白
        text = re.sub(r"\s+", " ", text).strip()
        # 超长兜底截断（尽量保持语义，硬上限100字）
        if len(text) > 100:
            text = text[:99].rstrip("，。,.、 ") + "。"
        return text

    @classmethod
    def clean(cls, text) -> str:
        """正则优化：去 think 标签、方括号【】、圆括号（）() 及分析性文字"""
        if not text:
            return ""
        text = str(text)
        text = cls._strip_think(text)

        # 分析性文字截断
        for kw in cls.ANALYSIS_KEYWORDS:
            idx = text.find(kw)
            if idx != -1:
                text = text[:idx].rstrip()
                break

        # 移除全角方括号【】及其内容、中英文圆括号及其内容
        text = re.sub(r"【[^】]*】", "", text)
        text = re.sub(r"（[^）]*）", "", text)
        text = re.sub(r"\([^)]*\)", "", text)

        # 清理多余空白与孤立标点
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()
