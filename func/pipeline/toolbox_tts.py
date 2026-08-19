# -*- coding: utf-8 -*-
# func/pipeline/toolbox_tts.py
# Toolbox 传递 TTS 桥接

import uuid

from func.log.default_log import DefaultLog


class ToolboxTtsBridge:
    """Toolbox → TTS 传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_answer_queue(self, llm_data, text: str, traceid: str = "",
                             seg_index: int = 0, chat_status: str = "end"):
        """将 toolbox 输出文本片段推送到 TTS 回答队列（空文本 + end 作为结束标记仍发送）"""
        if not text and chat_status != "end":
            return
        json_msg = {
            "voiceType": "chat",
            "traceid": traceid or str(uuid.uuid4()),
            "chatStatus": chat_status,
            "text": text,
            "language": "AutoChange",
            "seg_index": seg_index,
        }
        llm_data.AnswerList.put(json_msg)
