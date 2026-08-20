# -*- coding: utf-8 -*-
# func/llm/output.py
# LLM 流式输出处理：剥离 think/括号并分段送入 TTS 队列

import re
from typing import List

from func.pipeline.llm_tts import LLMTtsBridge


class Output:
    """流式输出处理器：逐字符过滤并分段推送到 TTS 队列"""

    def __init__(self, config, llm_data):
        self.split_chars: List[str] = config.split_chars
        self.split_limit: int = config.split_limit
        self.llm_data = llm_data
        self.tts_bridge = LLMTtsBridge()

        self.all_content = ""
        self.filtered_content = ""
        self.temp = ""
        self.segment_idx = 0
        self.chat_status = "start"
        self._in_think = False
        self._paren_depth = 0
        self._bracket_depth = 0
        self._tag = ""

    def process_chunk(self, chunk: str, traceid: str):
        """处理单个流式块：逐字符过滤后尝试分段发送"""
        if not chunk:
            return
        self.all_content += chunk
        for ch in chunk:
            self._feed(ch)
        self._split_send(traceid)

    def _feed(self, ch: str):
        """逐字符状态机：剥离 think 标签与中英文括号"""
        if self._tag:
            self._tag += ch
            if "<think>".startswith(self._tag) or "</think>".startswith(self._tag):
                if self._tag == "<think>":
                    self._in_think = True
                    self._tag = ""
                elif self._tag == "</think>":
                    self._in_think = False
                    self._tag = ""
                return
            self._flush_tag()
            return
        if ch == "<":
            self._tag = "<"
            return
        self._feed_plain(ch)

    def _flush_tag(self):
        """将误判为非 think 的标签缓冲按普通文本刷入"""
        tag, self._tag = self._tag, ""
        for c in tag:
            self._feed_plain(c)

    def _feed_plain(self, ch: str):
        """处理普通字符：think 内、括号内、方括号【】内丢弃，其余进入缓冲"""
        if self._in_think:
            return
        if ch == "【":
            self._bracket_depth += 1
            return
        if ch == "】":
            if self._bracket_depth > 0:
                self._bracket_depth -= 1
            return
        if self._bracket_depth > 0:
            return
        if ch in "（(":
            self._paren_depth += 1
            return
        if ch in "）)":
            if self._paren_depth > 0:
                self._paren_depth -= 1
            return
        if self._paren_depth == 0:
            self.temp += ch
            self.filtered_content += ch

    def _split_send(self, traceid: str):
        """按标点在达到最小长度后切分发送"""
        if len(self.temp) < self.split_limit:
            return
        last_punct_pos = -1
        for punct in self.split_chars:
            pos = self.temp.rfind(punct)
            if pos > last_punct_pos:
                last_punct_pos = pos
        if last_punct_pos == -1:
            return
        send_text = self.temp[:last_punct_pos + 1].strip()
        self.temp = self.temp[last_punct_pos + 1:]
        if not send_text:
            return
        self._send(send_text, traceid, self.chat_status)
        self.segment_idx += 1
        self.chat_status = ""

    def finalize(self, traceid: str) -> str:
        """结束流式：刷出剩余内容并返回清理后的完整文本"""
        if self._tag:
            self._flush_tag()
        if self.temp.strip():
            self._send(self.temp.strip(), traceid, "end")
        elif self.segment_idx == 0:
            if self.filtered_content.strip():
                self._send(self.filtered_content.strip(), traceid, "end")
        else:
            self.tts_bridge.send_to_answer_queue(
                self.llm_data, "", traceid,
                seg_index=self.segment_idx, chat_status="end"
            )
        return self.remove_analysis(self.filtered_content)

    def _send(self, text: str, traceid: str, chat_status: str):
        """通过桥接把文本片段推送到 TTS 队列"""
        self.tts_bridge.send_to_answer_queue(
            self.llm_data, text, traceid,
            seg_index=self.segment_idx,
            chat_status=chat_status
        )

    @staticmethod
    def remove_analysis(text: str) -> str:
        """移除分析性文字与括号内容"""
        keywords = ["这段对话", "这段文字", "这个对话"]
        for kw in keywords:
            idx = text.find(kw)
            if idx != -1:
                text = text[:idx].rstrip()
                break
        text = re.sub(r"（[^）]*）", "", text)
        text = re.sub(r"\([^)]*\)", "", text)
        return text.strip()
