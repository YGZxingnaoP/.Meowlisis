# -*- coding: utf-8 -*-
# func/llm/output.py
# LLM 流式输出处理：剥离 think/括号并分段送入 TTS 队列

import re
from typing import List

from func.log.default_log import DefaultLog
from func.pipeline.llm_tts import LLMTtsBridge


class Output:
    """流式输出处理器：逐字符过滤并分段推送到 TTS 队列"""

    # 参与连续标点合并的标点集合
    PUNCT_CHARS = set("，。！？!?,.;；:：、")

    def __init__(self, config, llm_data, enable_narration: bool = True):
        self.log = DefaultLog().getLogger()
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

        # 丰富性清洗：本轮开始按上一轮平滑得分取档位，边生成边清洗
        self.narration = None
        self.cleaner = None
        if enable_narration:
            try:
                from func.llm.narration.narration_core import NarrationCore
                nc = NarrationCore()
                if nc.enabled:
                    self.narration = nc
                    self.cleaner = nc.build_cleaner(nc.current_level())
            except Exception:
                self.log.exception("初始化丰富性清洗失败")
                self.narration = None
                self.cleaner = None

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
            self.filtered_content += ch
            if self.cleaner is not None:
                out = self.cleaner.feed(ch)
                for c in out:
                    if not self.temp and c in self.split_chars:
                        continue
                    self.temp += c
            else:
                self.temp += ch

    def send_preamble(self, text: str, traceid: str):
        """发送朗读前置段（弹幕朗读等），占用 seg_index=0，后续 LLM 回复从 1 开始。
        - 与 LLM 回复共享同一 traceid，TTS 按 traceid 归组为一个连续任务，中间不插入；
        - chat_status 置为空串（非 end），等待后续 LLM 回复段补全后统一结束。
        """
        if not text or not text.strip():
            return
        self.tts_bridge.send_to_answer_queue(
            self.llm_data, text.strip(), traceid,
            seg_index=0, chat_status=""
        )
        self.segment_idx = 1

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
        send_text = self._collapse_punctuation(send_text)
        if self._is_punct_only(send_text):
            return
        self._send(send_text, traceid, self.chat_status)
        self.segment_idx += 1
        self.chat_status = ""

    def finalize(self, traceid: str) -> str:
        """结束流式：刷出剩余内容并返回清理后的完整文本"""
        if self._tag:
            self._flush_tag()
        if self.cleaner is not None:
            tail = self.cleaner.flush()
            for c in tail:
                if not self.temp and c in self.split_chars:
                    continue
                self.temp += c
        tail_text = self._collapse_punctuation(self.temp.strip())
        if tail_text and not self._is_punct_only(tail_text):
            self._send(tail_text, traceid, "end")
        elif self.segment_idx == 0:
            cleaned = self.cleaner.cleaned if self.cleaner is not None else self.filtered_content
            cleaned_text = self._clean_punctuation(cleaned)
            if cleaned_text and not self._is_punct_only(cleaned_text):
                self._send(cleaned_text, traceid, "end")
        else:
            self.tts_bridge.send_to_answer_queue(
                self.llm_data, "", traceid,
                seg_index=self.segment_idx, chat_status="end"
            )
        # 本轮结束：用源文本（清洗前）更新平滑得分（空文本按 Raw=70 更新）
        if self.narration is not None:
            self.narration.update(self.filtered_content)
        if self.cleaner is not None:
            result = self._clean_punctuation(self.cleaner.cleaned)
        else:
            result = self._clean_punctuation(self.remove_analysis(self.filtered_content))
        return "" if self._is_punct_only(result) else result

    def _send(self, text: str, traceid: str, chat_status: str):
        """通过桥接把文本片段推送到 TTS 队列"""
        self.tts_bridge.send_to_answer_queue(
            self.llm_data, text, traceid,
            seg_index=self.segment_idx,
            chat_status=chat_status
        )

    @staticmethod
    def remove_analysis(text: str) -> str:
        """移除中英文圆括号内容"""
        text = re.sub(r"（[^）]*）", "", text)
        text = re.sub(r"\([^)]*\)", "", text)
        return text.strip()

    @staticmethod
    def clean_text(text: str) -> str:
        """一次性清洗完整回复文本：去 think 标签、方括号【】、圆括号（）() 内容"""
        if not text:
            return ""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"</?think>", "", text)
        text = re.sub(r"【[^】]*】", "", text)
        text = re.sub(r"（[^）]*）", "", text)
        text = re.sub(r"\([^)]*\)", "", text)
        return text.strip()

    @classmethod
    def split_text(cls, text: str, split_chars, split_limit: int) -> list:
        """一次性把完整文本切分为小句列表（与流式 _split_send 同规则）"""
        segments = []
        temp = ""
        for ch in text:
            temp += ch
            if len(temp) >= split_limit:
                last_punct_pos = -1
                for punct in split_chars:
                    pos = temp.rfind(punct)
                    if pos > last_punct_pos:
                        last_punct_pos = pos
                if last_punct_pos != -1:
                    seg = temp[:last_punct_pos + 1].strip()
                    temp = temp[last_punct_pos + 1:]
                    if seg:
                        segments.append(seg)
        if temp.strip():
            segments.append(temp.strip())
        return segments

    @staticmethod
    def _collapse_punctuation(text: str) -> str:
        """连续标点合并：两个及以上连续标点替换为一个句号，单个标点保留"""
        if not text:
            return text
        out = []
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch in Output.PUNCT_CHARS:
                j = i
                while j < n and text[j] in Output.PUNCT_CHARS:
                    j += 1
                if j - i >= 2:
                    out.append("。")
                else:
                    out.append(ch)
                i = j
            else:
                out.append(ch)
                i += 1
        return "".join(out)

    @staticmethod
    def _clean_punctuation(text: str) -> str:
        """水词清洗后的标点整理：先合并相邻标点为句号，再去掉句首残留标点"""
        if not text:
            return ""
        text = Output._collapse_punctuation(text.strip())
        i = 0
        while i < len(text) and text[i] in Output.PUNCT_CHARS:
            i += 1
        return text[i:]

    @staticmethod
    def _is_punct_only(text: str) -> bool:
        """判断文本是否只含标点/空白（无实质内容）"""
        for ch in text:
            if ch not in Output.PUNCT_CHARS and not ch.isspace():
                return False
        return True


def clean_and_split(text: str):
    """清洗完整回复文本并切分为小句，返回 (清洗后完整文本, 小句列表)。

    供非流式 LLM 回复（感想/内部回复/汇总）复用：记忆记录用清洗后完整文本，
    发送 TTS 用小句列表。
    """
    cleaned = Output.clean_text(text)
    if not cleaned:
        return "", []
    from func.llm.config import LLMConfig
    cfg = LLMConfig()
    return cleaned, Output.split_text(cleaned, cfg.split_chars, cfg.split_limit)
