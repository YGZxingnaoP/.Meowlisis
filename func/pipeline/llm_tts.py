# -*- coding: utf-8 -*-
# func/pipeline/llm_tts.py
# LLM 传递 TTS 桥接

from func.log.default_log import DefaultLog


class LLMTtsBridge:
    """LLM → TTS 传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_answer_queue(self, llm_data, text: str, traceid: str,
                             seg_index: int = 0, total_segments: int = 1,
                             chat_status: str = "end", question: str = ""):
        """将文本片段推送到 TTS 回答队列（空文本 + end 作为结束标记仍发送）"""
        if not text and chat_status != "end":
            return
        json_msg = {
            "voiceType": "chat",
            "traceid": traceid,
            "chatStatus": chat_status,
            "question": question,
            "text": text,
            "lanuage": "AutoChange",
            "seg_index": seg_index,
            "total_segments": total_segments
        }
        llm_data.AnswerList.put(json_msg)
