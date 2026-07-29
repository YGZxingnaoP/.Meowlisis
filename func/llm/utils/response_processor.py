# -*- coding: utf-8 -*-
"""
响应处理器：负责将 LLM 生成的文本进行分段、清理，并放入回答队列。
"""

import re
from typing import List, Dict, Any


class ResponseProcessor:
    """处理 LLM 响应，分段并推送到队列"""

    def __init__(self, split_chars: List[str], split_limit: int):
        """
        :param split_chars: 用于分段的标点符号列表
        :param split_limit: 分段的最小字符数
        """
        self.split_chars = split_chars
        self.split_limit = split_limit

    def split_text(self, text: str) -> List[str]:
        """
        将文本按标点分段，并合并过短的段
        :return: 分段后的文本列表
        """
        # 按标点拆分
        pattern = '|'.join(re.escape(c) for c in self.split_chars)
        segments = re.split(f'({pattern})', text)
        raw_sentences = []
        for i in range(0, len(segments) - 1, 2):
            raw_sentences.append(segments[i] + (segments[i + 1] if i + 1 < len(segments) else ''))
        if len(segments) % 2 == 1:
            raw_sentences.append(segments[-1])
        raw_sentences = [seg.strip() for seg in raw_sentences if seg.strip()]

        # 合并过短的段
        merged = []
        current = ""
        for sent in raw_sentences:
            if not current:
                current = sent
            else:
                if len(current) < self.split_limit:
                    current += sent
                else:
                    merged.append(current)
                    current = sent
        if current:
            merged.append(current)
        return merged if merged else [text]

    @staticmethod
    def remove_analysis(text: str) -> str:
        """移除文本中的分析性文字（如“这段对话”、“这段文字”等）"""
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
        """移除 <think> 标签及其内容"""
        return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)

    def process_and_queue(self, text: str, traceid: str, title: str,
                          answer_queue: Any, log_func=None) -> None:
        """
        处理文本：清理、分段、生成 JSON 并放入队列
        :param text: 原始文本
        :param traceid: 追踪 ID
        :param title: 用户问题（仅用于第一段）
        :param answer_queue: 回答队列
        :param log_func: 日志函数（可选）
        """
        # 清理
        text = self.remove_analysis(text)
        text = self.remove_think_tags(text)
        if not text:
            return

        # 分段
        segments = self.split_text(text)
        total = len(segments)

        for idx, seg in enumerate(segments):
            if total == 1:
                status = "end"
            else:
                if idx == 0:
                    status = "start"
                elif idx == total - 1:
                    status = "end"
                else:
                    status = ""

            json_str = {
                "voiceType": "chat",
                "traceid": traceid,
                "chatStatus": status,
                "question": title if idx == 0 else "",
                "text": seg,
                "lanuage": "AutoChange",
                "seg_index": idx,
                "total_segments": total
            }
            answer_queue.put(json_str)
            if log_func:
                log_func(f"[{traceid}]分段{idx + 1}/{total}: {seg}")


class StreamingResponseProcessor:
    """流式响应处理器，逐块处理并实时分段"""

    def __init__(self, split_chars: List[str], split_limit: int, on_chunk=None):
        self.split_chars = split_chars
        self.split_limit = split_limit
        self.on_chunk = on_chunk
        self.all_content = ""
        self.filtered_content = ""
        self.temp = ""
        self.segment_idx = 0
        self.chat_status = "start"
        self.prev_filtered_len = 0
        self.first_chunk_received = False

    def process_chunk(self, chunk: str, traceid: str, title: str,
                      answer_queue: Any, log_func=None) -> List[Dict]:
        """
        处理单个流式块，返回本次产生的分段 JSON 列表
        """
        if not self.first_chunk_received:
            self.first_chunk_received = True

        self.all_content += chunk

        # 实时过滤
        think_starts = len(re.findall(r'<think', self.all_content))
        think_ends = len(re.findall(r'</think>', self.all_content))
        in_think = think_starts > think_ends

        open_parens = len(re.findall(r'[\(（]', self.all_content))
        close_parens = len(re.findall(r'[\)）]', self.all_content))
        paren_depth = open_parens - close_parens
        if paren_depth < 0:
            paren_depth = 0
        in_paren = paren_depth > 0

        current_filtered = re.sub(r'<think>.*?</think>', '', self.all_content, flags=re.DOTALL)
        current_filtered = re.sub(r'\(.*?\)', '', current_filtered)
        current_filtered = re.sub(r'（.*?）', '', current_filtered)

        new_part = current_filtered[self.prev_filtered_len:]
        self.prev_filtered_len = len(current_filtered)
        self.filtered_content = current_filtered

        if not in_think and not in_paren:
            self.temp += new_part

        # 尝试分段
        produced = []
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
                    json_str = {
                        "voiceType": "chat",
                        "traceid": traceid,
                        "chatStatus": self.chat_status,
                        "question": title if self.segment_idx == 0 else "",
                        "text": send_text,
                        "lanuage": "AutoChange",
                        "seg_index": self.segment_idx,
                        "total_segments": -1
                    }
                    answer_queue.put(json_str)
                    if log_func:
                        log_func(f"[{traceid}] 流式分段{self.segment_idx + 1}: {send_text}")
                    self.segment_idx += 1
                    self.chat_status = ""
                    produced.append(json_str)
        if self.on_chunk:
            self.on_chunk(self.filtered_content, chunk)
        return produced

    def finalize(self, traceid: str, title: str, answer_queue: Any, log_func=None) -> None:
        """结束流式处理，输出剩余内容或结束标记"""
        if self.temp.strip():
            json_str = {
                "voiceType": "chat",
                "traceid": traceid,
                "chatStatus": "end",
                "question": "",
                "text": self.temp.strip(),
                "lanuage": "AutoChange",
                "seg_index": self.segment_idx,
                "total_segments": -1
            }
            answer_queue.put(json_str)
            if log_func:
                log_func(f"[{traceid}] 流式最后分段: {self.temp.strip()}")
        else:
            if self.segment_idx == 0:
                if self.filtered_content.strip():
                    json_str = {
                        "voiceType": "chat",
                        "traceid": traceid,
                        "chatStatus": "end",
                        "question": title,
                        "text": self.filtered_content.strip(),
                        "lanuage": "AutoChange",
                        "seg_index": 0,
                        "total_segments": 1
                    }
                    answer_queue.put(json_str)
                    if log_func:
                        log_func(f"[{traceid}] 流式全文本: {self.filtered_content.strip()}")
            else:
                json_str = {
                    "voiceType": "chat",
                    "traceid": traceid,
                    "chatStatus": "end",
                    "question": "",
                    "text": "",
                    "lanuage": "AutoChange",
                    "seg_index": self.segment_idx,
                    "total_segments": -1
                }
                answer_queue.put(json_str)
                if log_func:
                    log_func(f"[{traceid}] 流式结束标记发送")