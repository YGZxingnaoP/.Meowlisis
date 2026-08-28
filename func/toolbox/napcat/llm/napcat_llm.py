# -*- coding: utf-8 -*-
# func/toolbox/napcat/llm/napcat_llm.py
# NapCat 独立 LLM 回复链路：流式生成 → 正则过滤 → 短句切分 → 通过回调回传

import re
from typing import List, Optional, Callable

from func.log.default_log import DefaultLog
from func.llm.config import LLMConfig
from func.toolbox.napcat.config import TBNapCatConfig


class TBNapCatLLM:
    """NapCat 回复 LLM：复用 func/llm 配置，使用 toolbox port 流式调用，max_tokens 特殊处理。

    本类不直接发送消息，也不直接操作 napcat_core；只负责生成与切分，
    短句通过 on_segment 回调回传给上层（toolbox_core），由上层统一发送。
    """

    # 切分并忽略的标点（逗号、句号、问号）
    SPLIT_IGNORE = "，。？,.?"
    # nsfw 模式切割减小：不按逗号切，一段容纳更多小句
    SPLIT_IGNORE_NSFW = "。？.?"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.cfg = LLMConfig()
        self.napcat_cfg = TBNapCatConfig()
        self._max_tokens = None
        # nsfw 切割模式（本次回复是否减少切割点）
        self._nsfw_split = False
        # 流式过滤状态（与 TTS 一致的 think/括号剥离）
        self._in_think = False
        self._paren_depth = 0
        self._bracket_depth = 0
        self._tag = ""
        self._temp = ""
        self._filtered = ""

    def _llm(self):
        """创建 toolbox port 流式客户端（复用 func/llm 配置，medium 思考由 thinking_level 控制）"""
        if self.cfg.local_llm_type == "gemini":
            from func.toolbox.port.gemini import TBoxGeminiLLM
            return TBoxGeminiLLM(self.cfg), self.cfg.gemini_max_tokens
        if self.cfg.local_llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(self.cfg), self.cfg.aliyun_max_tokens
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(self.cfg), self.cfg.deepseek_max_tokens

    def _system_prompt(self, username: str, current_message: str, user_id: str = "") -> str:
        """获取 napcat 专用系统提示词（前置词 + 你在QQ里回复）"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            return SystemPromptBridge().get_napcat_prompt(username, current_message, user_id=user_id)
        except Exception:
            self.log.exception("获取 napcat 系统提示词失败")
            return ""

    def _generate(self, messages: List[dict]) -> str:
        # 流式生成并累积完整回复，不发送
        llm, base_max_tokens = self._llm()
        if llm is None or not llm.client:
            self.log.error("NapCat 回复 LLM 不可用")
            return ""
        if self._max_tokens is None:
            self._max_tokens = max(8, int(base_max_tokens) + 128)
        self._reset_filter()

        stream = llm.chat_stream(
            messages,
            options={"max_tokens": self._max_tokens},
            thinking_level=self.napcat_cfg.thinking_level,
        )
        reasoning_len = 0
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "reasoning_content", None):
                reasoning_len += len(delta.reasoning_content)
            if not delta.content:
                continue
            for ch in delta.content:
                self._feed(ch)
        if self._tag:
            self._flush_tag()
        if self._temp.strip():
            self._temp = ""

        final = self.remove_analysis(self._filtered).strip()
        if not final:
            self.log.warning(
                f"[NapCat] 回复为空！reasoning_content 长度={reasoning_len}，"
                f"max_tokens={self._max_tokens}。若思考模式开启，可能是 max_tokens 太小被思考占满"
            )
        return final

    def _rewrite_if_too_long(self, messages: List[dict], final: str, word_count: int) -> str:
        # 超长驳回重写：最多重写3次，仍超长直接发送不截断
        limit = int(word_count or 10) + 10
        for _ in range(3):
            if len(final) <= limit:
                break
            messages.append({
                "role": "user",
                "content": "你上次的回复超过字数上限，被驳回了。最高准则：回复字数严格控制小于10字，请重新回复，只输出回复内容本身。",
            })
            final = self._generate(messages)
        return final

    def reply_stream(self, system_prompt: str, messages: List[dict],
                     on_segment: Optional[Callable[[str], None]] = None) -> str:
        """通用流式回复：自定义 system prompt 与历史消息，流式过滤/切分后回传。

        - 返回清理后的完整回复文本；
        - on_segment 回调逐段回传（供 napcat 发送、戳一戳发牢骚等复用）。
        """
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages or [])
        final = self._generate(full_messages)
        for seg in self.split_segments(final):
            if on_segment and seg:
                on_segment(seg)
        return final

    def reply(self, username: str, user_id: str, text: str, short_memory: List[dict],
              on_segment: Optional[Callable[[str], None]] = None,
              nsfw: bool = False) -> str:
        """流式生成回复（NapCat 私聊）：组装 napcat 提示词 + 短期记忆 + 当前消息

        nsfw=True 时切割减小（不按逗号切），一段容纳更多内容。
        """
        self._nsfw_split = bool(nsfw)
        try:
            system_prompt = self._system_prompt(username, text, user_id)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            for m in short_memory or []:
                if m.get("role") in ("user", "assistant") and m.get("content"):
                    messages.append({"role": m["role"], "content": m["content"]})
            messages.append({"role": "user", "content": text})
            final = self._generate(messages)
            final = self._rewrite_if_too_long(messages, final, int(self.napcat_cfg.reply_word_count or 10))
            for seg in self.split_segments(final):
                if on_segment and seg:
                    on_segment(seg)
            self.log.info(f"[NapCat] 回复 {username}: {final[:50]}...")
            return final
        finally:
            self._nsfw_split = False

    # ==================== 过滤与切分 ====================
    def _reset_filter(self):
        self._in_think = False
        self._paren_depth = 0
        self._bracket_depth = 0
        self._tag = ""
        self._temp = ""
        self._filtered = ""

    def _feed(self, ch: str):
        """逐字符状态机：剥离 think 标签与中英文括号内容（与 TTS Output 一致）"""
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
        tag, self._tag = self._tag, ""
        for c in tag:
            self._feed_plain(c)

    def _feed_plain(self, ch: str):
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
            self._temp += ch
            self._filtered += ch

    @classmethod
    def split_segments(cls, text: str) -> List[str]:
        # 按逗号/句号/问号切分，忽略标点，感叹号保留
        if not text:
            return []
        segs = []
        out = ""
        for ch in text:
            if ch in cls.SPLIT_IGNORE:
                if out.strip():
                    segs.append(out.strip())
                out = ""
            else:
                out += ch
        if out.strip():
            segs.append(out.strip())
        return segs

    def _split(self):
        """按标点切分并忽略标点，感叹号保留不切分。

        nsfw 模式使用 SPLIT_IGNORE_NSFW（不按逗号切），一段容纳更多小句。
        """
        ignore = self.SPLIT_IGNORE_NSFW if self._nsfw_split else self.SPLIT_IGNORE
        segs = []
        out = ""
        for ch in self._temp:
            if ch in ignore:
                if out.strip():
                    segs.append(out.strip())
                out = ""
            else:
                out += ch
        self._temp = out
        return segs

    @staticmethod
    def remove_analysis(text: str) -> str:
        """移除中英文圆括号内容（与 TTS Output 一致）"""
        if not text:
            return ""
        text = re.sub(r"（[^）]*）", "", text)
        text = re.sub(r"\([^)]*\)", "", text)
        return text.strip()
