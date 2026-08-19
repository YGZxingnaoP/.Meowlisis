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

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.cfg = LLMConfig()
        self.napcat_cfg = TBNapCatConfig()
        self._max_tokens = None
        # 流式过滤状态（与 TTS 一致的 think/括号剥离）
        self._in_think = False
        self._paren_depth = 0
        self._tag = ""
        self._temp = ""
        self._filtered = ""

    def _llm(self):
        """创建 toolbox port 流式客户端（复用 func/llm 配置，medium 思考由 thinking_level 控制）"""
        if self.cfg.local_llm_type == "aliyun":
            from func.toolbox.port.aliyun import TBoxAliyunLLM
            return TBoxAliyunLLM(self.cfg), self.cfg.aliyun_max_tokens
        from func.toolbox.port.deepseek import TBoxDeepSeekLLM
        return TBoxDeepSeekLLM(self.cfg), self.cfg.deepseek_max_tokens

    def _system_prompt(self, username: str, current_message: str) -> str:
        """获取 napcat 专用系统提示词（前置词 + 你在QQ里回复）"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            return SystemPromptBridge().get_napcat_prompt(username, current_message)
        except Exception:
            self.log.exception("获取 napcat 系统提示词失败")
            return ""

    def reply(self, username: str, user_id: str, text: str, short_memory: List[dict],
              on_segment: Optional[Callable[[str], None]] = None) -> str:
        """流式生成回复，正则过滤后按短句切分，通过 on_segment 回传；返回完整回复文本"""
        llm, base_max_tokens = self._llm()
        if llm is None or not llm.client:
            self.log.error("NapCat 回复 LLM 不可用")
            return ""
        # max_tokens：直接使用 func/llm 配置值（不再做 /4 或 ×2 的特殊处理）
        if self._max_tokens is None:
            self._max_tokens = max(8, int(base_max_tokens))
        self._reset_filter()

        system_prompt = self._system_prompt(username, text)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in short_memory or []:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": text})

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
            # 思考内容仅统计长度用于诊断，不回传给用户
            if getattr(delta, "reasoning_content", None):
                reasoning_len += len(delta.reasoning_content)
            if not delta.content:
                continue
            for ch in delta.content:
                self._feed(ch)
            for seg in self._split():
                if on_segment:
                    on_segment(seg)
        # 刷出残留 think 标签与剩余缓冲
        if self._tag:
            self._flush_tag()
        if self._temp.strip():
            seg = self._temp.strip()
            self._temp = ""
            if on_segment:
                on_segment(seg)

        final = self.remove_analysis(self._filtered).strip()
        if not final:
            self.log.warning(
                f"[NapCat] 回复为空！reasoning_content 长度={reasoning_len}，"
                f"max_tokens={self._max_tokens}。若思考模式开启，可能是 max_tokens 太小被思考占满"
            )
        self.log.info(f"[NapCat] 回复 {username}: {final[:50]}...")
        return final

    # ==================== 过滤与切分 ====================
    def _reset_filter(self):
        self._in_think = False
        self._paren_depth = 0
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

    def _split(self):
        """按逗号/句号/问号切分并忽略标点，感叹号保留不切分"""
        segs = []
        out = ""
        for ch in self._temp:
            if ch in self.SPLIT_IGNORE:
                if out.strip():
                    segs.append(out.strip())
                out = ""
            else:
                out += ch
        self._temp = out
        return segs

    @staticmethod
    def remove_analysis(text: str) -> str:
        """移除分析性文字与括号内容（与 TTS Output 一致）"""
        if not text:
            return ""
        keywords = ["这段对话", "这段文字", "这个对话"]
        for kw in keywords:
            idx = text.find(kw)
            if idx != -1:
                text = text[:idx].rstrip()
                break
        text = re.sub(r"（[^）]*）", "", text)
        text = re.sub(r"\([^)]*\)", "", text)
        return text.strip()
