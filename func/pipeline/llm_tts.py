# -*- coding: utf-8 -*-
# func/pipeline/llm_tts.py
# LLM 传递 TTS 桥接

from func.log.default_log import DefaultLog


class LLMTtsBridge:
    """LLM → TTS 传递桥接"""

    def __init__(self):
        self.log = DefaultLog().getLogger()

    def send_to_answer_queue(self, llm_data, text: str, traceid: str,
                             seg_index: int = 0, chat_status: str = "end",
                             source: str = "llm"):
        """将文本片段推送到 TTS 回答队列（空文本 + end 作为结束标记仍发送）"""
        if not text and chat_status != "end":
            return
        json_msg = {
            "voiceType": "chat",
            "source": source,
            "traceid": traceid,
            "chatStatus": chat_status,
            "text": text,
            "language": "AutoChange",
            "seg_index": seg_index,
        }
        llm_data.AnswerList.put(json_msg)

    def send_chat_segment(self, text: str, traceid: str, seg_index: int = 0,
                          chat_status: str = "end", source: str = "llm"):
        """不持有 llm 运行时对象的推送口：供 llm_active 导演副本使用。

        pipeline 层内部取 LLmState（与 toolbox_tts 同一模式），
        调用方只传文本数据，不 import llm 层状态对象。
        """
        from func.llm.state import LLmState
        self.send_to_answer_queue(LLmState(), text, traceid,
                                  seg_index=seg_index, chat_status=chat_status,
                                  source=source)

    def send_whole_to_answer_queue(self, llm_data, text: str, traceid: str,
                                   source: str = "llm"):
        """将整段文本一次性推送到 TTS 回答队列（不分段，供主动回复 inherit 使用）"""
        if not text:
            return
        json_msg = {
            "voiceType": "chat",
            "source": source,
            "traceid": traceid,
            "chatStatus": "end",
            "text": text,
            "language": "AutoChange",
        }
        llm_data.AnswerList.put(json_msg)
