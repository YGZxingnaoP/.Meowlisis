# -*- coding: utf-8 -*-
"""模式切换判定：论文 §3.2 / 附录 B 的那一句 yes/no 提问。

机制（严格按论文）
------------------
每 `probe_every` 个 decode step（或思考流出现 `\\n\\n`），把问句写进**独立的
QUESTION 块**，用 mode 视图 `M -> T -> W -> Q` 做一次前向，读下一个 token 上
"yes" 与 "no" 的概率质量：

    p(yes) > p(no)  -> 允许 writer 继续写
    否则             -> 立刻冻结 writer，只推 thinker，直到下一次 yes

问句**逐字**取自官方 prompting.py。`yes_bias` 对应论文 Figure 4 里的
"AsyncReasoning (+Δ)"：给 yes 的对数概率加一个固定偏置（论文里 Δ=+0.1/+0.5
是显式对比项），用来把判定往"继续写"那边推。

本模块只管"问什么 / 怎么判"，真正的 KV 操作在 `loop._probe()`。
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

#: 论文附录 B 的 Mode Switching question，逐字（注意原文就是 "my current thoughts"）
PROBE_QUESTION = (
    "...\n\nWait, are my current thoughts enough to write the next paragraph or formula? "
    "(yes/no): "
)

#: 代表"可以继续写"与"得再想想"的字面量（只看首 token）
YES_WORDS = ("yes", " yes", "Yes", " Yes")
NO_WORDS = ("no", " no", "No", " No")


@dataclass
class ModeDecision:
    """一次探针判定的结果。"""

    continue_speaking: bool
    p_yes: float
    p_no: float
    note: str = ""


class ModeController:
    """按步数触发探针，并用 yes/no 的概率质量做二分类。"""

    def __init__(self, tokenizer, probe_every: int = 20,
                 yes_bias: float = 0.0) -> None:
        self.tok = tokenizer
        self.every = max(1, int(probe_every))
        self.yes_bias = float(yes_bias)
        #: 问句 token（每轮直接写进 QUESTION 块，不经过思考流）
        self.question_ids = self._encode(PROBE_QUESTION)
        self._yes_ids = self._first_token_ids(YES_WORDS)
        self._no_ids = self._first_token_ids(NO_WORDS)
        self._since = 0

    # ------------------------------------------------------------------ 工具
    def _encode(self, text: str) -> list[int]:
        try:
            return [int(t) for t in self.tok.encode(text, add_special_tokens=False)]
        except Exception:  # noqa: BLE001 - 分词器异常不该让生成崩
            return []

    def _first_token_ids(self, words: tuple[str, ...]) -> set[int]:
        """把若干词面转成"首 token id"集合。"""
        ids: set[int] = set()
        for word in words:
            encoded = self._encode(word)
            if encoded:
                ids.add(encoded[0])
        return ids

    # ------------------------------------------------------------------ 触发
    def tick(self) -> bool:
        """每个 decode step 调一次；返回是否该问。"""
        self._since += 1
        if self._since >= self.every:
            self._since = 0
            return True
        return False

    def reset_counter(self) -> None:
        """暂停/判定之后重新起算。"""
        self._since = 0

    # ------------------------------------------------------------------ 判定
    def decide(self, logits: torch.Tensor) -> ModeDecision:
        """用"下一个 token"的 logits 判 yes / no。

        logits 形状 (vocab,) 或 (1, vocab)。yes/no 任一集合解析不出来时保守继续。
        """
        if not self._yes_ids or not self._no_ids:
            return ModeDecision(True, 0.0, 0.0, "yes/no 首 token 未解析出来，保守继续")

        vector = logits.reshape(-1).float()
        if self.yes_bias:
            vector = vector.clone()
            idx = torch.tensor(sorted(self._yes_ids), device=vector.device,
                               dtype=torch.long)
            vector[idx] += self.yes_bias
        probs = torch.softmax(vector, dim=-1)

        def mass(ids: set[int]) -> float:
            index = torch.tensor(sorted(ids), device=probs.device, dtype=torch.long)
            return float(probs[index].sum().item())

        p_yes = mass(self._yes_ids)
        p_no = mass(self._no_ids)
        return ModeDecision(continue_speaking=p_yes > p_no, p_yes=p_yes, p_no=p_no)
