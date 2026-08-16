# -*- coding: utf-8 -*-
# func/llm/output.py
# 流式输出处理：正则优化 + 分段 + 发送 TTS

import re
from typing import List

from func.pipeline.llm_tts import LLMTtsBridge


class Output:
    """流式输出处理器，逐块累积、过滤、分段并推送到 TTS 队列"""

    def __init__(self, config, llm_data):
        self.split_chars: List[str] = config.split_chars
        self.split_limit: int = config.split_limit
        self.llm_data = llm_data
        self.tts_bridge = LLMTtsBridge()

        # 流式累积状态
        self.all_content = ""
        self.filtered_content = ""
        self.temp = ""
        self.segment_idx = 0
        self.chat_status = "start"
        self.prev_filtered_len = 0
        self.first_chunk_received = False

    def process_chunk(self, chunk: str, traceid: str, title: str):
        """处理单个流式块，实时过滤括号/think 并按标点分段发送"""
        if not self.first_chunk_received:
            self.first_chunk_received = True

        self.all_content += chunk

        # 实时判断是否处于 think 标签或括号内部
        think_starts = len(re.findall(r'<think', self.all_content))
        think_ends = len(re.findall(r'</think>', self.all_content))
        in_think = think_starts > think_ends

        open_parens = len(re.findall(r'[\(（]', self.all_content))
        close_parens = len(re.findall(r'[\)）]', self.all_content))
        paren_depth = open_parens - close_parens
        if paren_depth < 0:
            paren_depth = 0
        in_paren = paren_depth > 0

        # 实时过滤 think 标签与中英文括号
        current_filtered = re.sub(r'<think>.*?</think>', '', self.all_content, flags=re.DOTALL)
        current_filtered = re.sub(r'\(.*?\)', '', current_filtered)
        current_filtered = re.sub(r'（.*?）', '', current_filtered)

        new_part = current_filtered[self.prev_filtered_len:]
        self.prev_filtered_len = len(current_filtered)
        self.filtered_content = current_filtered

        if not in_think and not in_paren:
            self.temp += new_part

        # 达到最小长度后按最后一个标点切分发送
        if not in_think and not in_paren and len(self.temp) >= self.split_limit:
            last_punct_pos = -1
            for punct in self.split_chars:
                pos = self.temp.rfind(punct)
                if pos > last_punct_pos:
                    last_punct_pos = pos
            if last_punct_pos != -1:
                send_text = self.temp[:last_punct_pos + 1].strip()
                self.temp = self.temp[last_punct_pos + 1:]
                if send_text:
                    question = title if self.segment_idx == 0 else ""
                    self._send(send_text, traceid, question, self.chat_status)
                    self.segment_idx += 1
                    self.chat_status = ""

    def finalize(self, traceid: str, title: str) -> str:
        """结束流式，输出剩余内容，返回清理后的完整文本"""
        if self.temp.strip():
            self._send(self.temp.strip(), traceid, "", "end")
        elif self.segment_idx == 0:
            if self.filtered_content.strip():
                self._send(self.filtered_content.strip(), traceid, title, "end")
        else:
            # 发送结束标记
            self.tts_bridge.send_to_answer_queue(
                self.llm_data, "", traceid,
                seg_index=self.segment_idx, total_segments=-1, chat_status="end"
            )
        # 返回清理后的完整文本（用于写入短期记忆）
        return self.remove_analysis(self.filtered_content)

    def _send(self, text: str, traceid: str, question: str, chat_status: str):
        """通过 pipeline 的 llm_tts 桥接发送文本片段到 TTS 队列"""
        self.tts_bridge.send_to_answer_queue(
            self.llm_data, text, traceid,
            seg_index=self.segment_idx, total_segments=-1,
            chat_status=chat_status, question=question
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
        text = re.sub(r'（[^）]*）', '', text)
        text = re.sub(r'\([^)]*\)', '', text)
        return text.strip()

    @staticmethod
    def remove_think_tags(text: str) -> str:
        """移除 think 标签及其内容"""
        return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
