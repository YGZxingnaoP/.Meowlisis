# -*- coding: utf-8 -*-
# func/pipeline/toolbox_tts.py
# Toolbox 传递 TTS 桥接

import re
import uuid

from func.log.default_log import DefaultLog


class ToolboxTtsBridge:
    """Toolbox → TTS 传递桥接

    本桥接在 pipeline 层内部持有 LLmState（AnswerList），
    toolbox 层只传递文本数据，不再直接 import/操作 llm 层状态对象。
    """

    # 分段标点（与主 LLM 一致，按这些标点切分成多个 TTS 片段）
    SPLIT_CHARS = [",", "，", "。", "!", "！", "?", "？", "；", ";"]

    def __init__(self):
        self.log = DefaultLog().getLogger()
        # pipeline 层自己持有 TTS 回答队列所属状态，封装 llm 层运行时对象
        from func.llm.state import LLmState
        self.llm_data = LLmState()

    def send_to_answer_queue(self, text: str, traceid: str = "",
                             seg_index: int = 0, chat_status: str = "end",
                             source: str = "toolbox"):
        """将 toolbox 输出文本片段推送到 TTS 回答队列（空文本 + end 作为结束标记仍发送）

        - source 仅作来源标注（如 toolbox / toolbox_watching），不作为 TTS 分组键。
        """
        if not text and chat_status != "end":
            return
        json_msg = {
            "voiceType": "chat",
            "source": source or "toolbox",
            "traceid": traceid or str(uuid.uuid4()),
            "chatStatus": chat_status,
            "text": text,
            "language": "AutoChange",
            "seg_index": seg_index,
        }
        self.llm_data.AnswerList.put(json_msg)

    def send_stream(self, text: str, source: str = "toolbox"):
        """把整段文本按标点切分后逐段送入 TTS（seg_index 递增，最后 end）。

        实现「边合成边播放」的流式效果：与主 LLM 分段逻辑一致，
        weather/news/vision 等工具箱整段回复也走分段，不再整段合成完才播放。
        """
        if not text or not text.strip():
            return
        traceid = str(uuid.uuid4())
        segments = self._split(text.strip())
        if not segments:
            self.send_to_answer_queue(text.strip(), traceid=traceid,
                                      seg_index=0, chat_status="end", source=source)
            return
        for i, seg in enumerate(segments):
            chat_status = "end" if i == len(segments) - 1 else ""
            self.send_to_answer_queue(seg, traceid=traceid,
                                      seg_index=i, chat_status=chat_status, source=source)

    def is_busy(self) -> bool:
        """检测当前是否有 TTS 说话任务（供弹幕消费调度轮询）。

        - True 表示正在说话/有排队任务，弹幕只进队列不传递；
        - False 表示空闲，可立即消费弹幕队列。
        """
        try:
            from func.tts.tts_core import TTsCore
            return TTsCore().is_busy()
        except Exception:
            self.log.exception("检测 TTS 忙状态失败")
            return False

    @classmethod
    def _split(cls, text: str) -> list:
        """按标点切分文本为多个片段（保留标点，过滤空段）"""
        result = []
        buf = ""
        for ch in text:
            buf += ch
            if ch in cls.SPLIT_CHARS:
                seg = buf.strip()
                if seg:
                    result.append(seg)
                buf = ""
        if buf.strip():
            result.append(buf.strip())
        return result
