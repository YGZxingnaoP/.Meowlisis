# -*- coding: utf-8 -*-
"""模式切换：让模型自己决定"现在该不该暂停输出"。

机制（论文 §3.2）
-----------------
每段结束**或**每 T=20 个思考 token，在思考流末尾插入一句探针，然后看下一个
token 上 "yes" 与 "no" 的概率：

    yes 更可能 -> 继续并行（边想边说）
    no  更可能 -> 冻结 Writer，只推 Thinker，直到再次出现 yes

判完要把探针这几个 token 的 KV **从视野里隐藏**，否则会污染后续思维链。

本模块只负责"要不要暂停"的判定与探针文本；具体的隐藏动作由 `loop` 完成
（它持有真正的 KV）。
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from meowllm.engine.dualstream.prompts import pick

#: 探针文本 —— **逐字**取自官方 prompting.py 的 mode_switching_question
PROBE_EN = (
    "...\n\nWait, are my current thoughts enough to write the next paragraph or formula? "
    "(yes/no): "
)
PROBE_ZH = "\n\n等等，我现在的想法够写下一段了吗？(够/不够): "

#: 各语言下代表"够/继续"与"不够/暂停"的字面量
_AFFIRMATIVE = {
    "en": ("yes", "Yes", " yes", " Yes"),
    "zh": ("够", "够的", "是的", "可以"),
}
_NEGATIVE = {
    "en": ("no", "No", " no", " No"),
    "zh": ("不够", "不", "还没"),
}


@dataclass
class ModeDecision:
    """一次探针判定的结果。"""

    continue_speaking: bool
    p_yes: float
    p_no: float
    note: str = ""

    @property
    def enough(self) -> bool:
        return self.continue_speaking


PROBE_ROLEPLAY_EN = (
    "\n\n...\n\nI can add one more concrete detail here if it is worth saying. "
    "Add it now? (yes/no): "
)
PROBE_ROLEPLAY_ZH = "\n\n……\n\n这里还能再补一句具体的细节，要补吗？(要/不要): "

_ROLEPLAY_AFFIRMATIVE = {
    "en": ("yes", "Yes", " yes", " Yes"),
    "zh": ("要", "有", "好", "是", "补"),
}
_ROLEPLAY_NEGATIVE = {
    "en": ("no", "No", " no", " No"),
    "zh": ("不要", "不", "没", "不用"),
}


class ModeController:
    """按间隔触发探针，并用 token 概率做二分类判定。"""

    def __init__(self, tokenizer, language: str = "zh",
                 probe_every_tokens: int = 20,
                 probe_kind: str = "roleplay") -> None:
        self.tok = tokenizer
        self.language = language
        self.probe_kind = probe_kind if probe_kind in ("roleplay", "math") else "roleplay"
        if self.probe_kind == "roleplay":
            self.probe_text = PROBE_ROLEPLAY_ZH if language == "zh" else PROBE_ROLEPLAY_EN
            affirmative = _ROLEPLAY_AFFIRMATIVE
            negative = _ROLEPLAY_NEGATIVE
        else:
            self.probe_text = PROBE_ZH if language == "zh" else PROBE_EN
            affirmative = _AFFIRMATIVE
            negative = _NEGATIVE
        self.every = max(1, int(probe_every_tokens))
        self._yes_ids = self._first_token_ids(affirmative.get(language, ()))
        self._no_ids = self._first_token_ids(negative.get(language, ()))
        self._since_probe = 0

    # ------------------------------------------------------------------ 工具
    def _first_token_ids(self, words: tuple[str, ...]) -> set[int]:
        """把若干词面转成"首 token id"集合。"""
        ids: set[int] = set()
        for word in words:
            try:
                encoded = self.tok.encode(word, add_special_tokens=False)
            except Exception:  # noqa: BLE001
                continue
            if encoded:
                ids.add(int(encoded[0]))
        return ids

    # ------------------------------------------------------------------ 触发
    def tick(self, new_tokens: int = 1) -> bool:
        """每生成一个思考 token 调一次；返回是否该插探针。"""
        self._since_probe += int(new_tokens)
        if self._since_probe >= self.every:
            self._since_probe = 0
            return True
        return False

    def reset_counter(self) -> None:
        """段落边界等外部事件也可主动清零。"""
        self._since_probe = 0

    # ------------------------------------------------------------------ 判定
    def decide(self, logits: torch.Tensor) -> ModeDecision:
        """用"下一个 token"的 logits 判断 yes / no。

        logits 形状 (vocab,) 或 (1, vocab)，取最后一维做 softmax。
        两个 id 集合任意一边为空时视为判定失败（`continue_speaking=True`，即保守地继续）。
        """
        vector = logits.reshape(-1).float()
        probs = torch.softmax(vector, dim=-1)

        def mass(ids: set[int]) -> float:
            if not ids:
                return 0.0
            index = torch.tensor(sorted(ids), device=probs.device, dtype=torch.long)
            return float(probs[index].sum().item())

        p_yes = mass(self._yes_ids)
        p_no = mass(self._no_ids)

        if not self._yes_ids or not self._no_ids:
            return ModeDecision(True, p_yes, p_no,
                                note="yes/no 首 token 未解析出来，保守继续")
        return ModeDecision(continue_speaking=p_yes >= p_no, p_yes=p_yes, p_no=p_no)

    # ------------------------------------------------------------------ 文本
    def system_pair(self) -> dict[str, str]:
        """取当前语言的视图提示（给 loop 拼 prompt 用）。"""
        return pick(self.language)
