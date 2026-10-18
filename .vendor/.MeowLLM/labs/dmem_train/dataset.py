# -*- coding: utf-8 -*-
"""δ-mem 训练用的数据集：编码、统计、切分。

一条样本（JSONL 一行）：
    {"id": "...", "context": "...", "query": "...", "response": "...",
     "segments": [23, 31, ...], "source": "abstract_memory/llm"}

约定（和论文 §3.6 一致，也和 `meowllm/dmem` 的推理路径一致）：
    * context 只进状态，**不进** backbone 输入；
    * query 用 Qwen3 的 chat template 渲染（带 generation prompt），
      保证训练与推理的 prompt 形态一模一样；
    * response 后面补 `<|im_end|>`，loss 只算 response 这一段。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field


@dataclass
class EncodedSample:
    """编码后的一条样本（都是 python list[int]，方便排查）。"""

    ctx_ids: list[int] = field(default_factory=list)
    input_ids: list[int] = field(default_factory=list)
    labels: list[int] = field(default_factory=list)
    segments: list[int] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def answer_len(self) -> int:
        return sum(1 for t in self.labels if t != -100)


def read_jsonl(path: str) -> list[dict]:
    rows = []
    # utf-8-sig：Windows 上手工/脚本造出来的 jsonl 常带 BOM
    with open(path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: str, rows: list[dict]) -> int:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def encode_sample(tok, row: dict, context_len: int = 1024,
                  answer_len: int = 256, max_context_tokens: int = 8192) -> EncodedSample:
    """把一行样本编码成 (context, query+response, labels)。"""
    ctx_ids = tok(row.get("context") or "", add_special_tokens=False,
                  truncation=True,
                  max_length=min(int(context_len), int(max_context_tokens)))["input_ids"]
    messages = [{"role": "user", "content": str(row.get("query") or "")}]
    prompt = tok.apply_chat_template(messages, add_generation_prompt=True,
                                     tokenize=False)
    prompt_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    answer_ids = tok(str(row.get("response") or ""), add_special_tokens=False,
                     truncation=True, max_length=int(answer_len))["input_ids"]
    eos = tok.convert_tokens_to_ids("<|im_end|>")
    if isinstance(eos, int) and eos >= 0:
        answer_ids = answer_ids + [eos]
    input_ids = list(prompt_ids) + list(answer_ids)
    labels = [-100] * len(prompt_ids) + list(answer_ids)
    segments = [int(x) for x in (row.get("segments") or []) if int(x) > 0]
    return EncodedSample(ctx_ids=ctx_ids, input_ids=input_ids, labels=labels,
                         segments=segments, meta={"id": row.get("id"),
                                                  "source": row.get("source")})


def split_rows(rows: list[dict], holdout_ratio: float = 0.05,
               seed: int = 42) -> tuple[list[dict], list[dict]]:
    """切训练/留出。优先按 `event_id` 分组，避免同一记忆事件泄漏到两边。

    `event_id` 由 build_data.py 写入（事件文本的 hash）。没有这个字段时退回按
    id 前缀分组 —— 那样只能防"同一批合成"的泄漏，防不住"同一事件不同问法"。
    """
    rng = random.Random(seed)
    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = str(row.get("event_id") or "")
        if not key:
            key = str(row.get("source") or "") + "|" + str(row.get("id") or "")
        groups.setdefault(key, []).append(row)
    keys = list(groups)
    rng.shuffle(keys)
    take = max(1, int(len(keys) * holdout_ratio)) if len(keys) > 8 else 0
    hold_keys = set(keys[:take])
    train, holdout = [], []
    for key in keys:
        (holdout if key in hold_keys else train).extend(groups[key])
    return train, holdout


def dataset_stats(rows: list[dict], tok, context_len: int = 1024,
                  answer_len: int = 256) -> dict:
    """看一眼数据规模/长度分布，训练前必查。"""
    if not rows:
        return {"rows": 0}
    sample = rows[: min(len(rows), 64)]
    ctx, ans = [], []
    for row in sample:
        enc = encode_sample(tok, row, context_len, answer_len)
        ctx.append(len(enc.ctx_ids))
        ans.append(enc.answer_len)
    sources: dict[str, int] = {}
    for row in rows:
        key = str(row.get("source") or "?")
        sources[key] = sources.get(key, 0) + 1
    ctx.sort()
    ans.sort()
    return {
        "rows": len(rows),
        "sources": sources,
        "context_tokens_p50": ctx[len(ctx) // 2],
        "context_tokens_max": ctx[-1],
        "answer_tokens_p50": ans[len(ans) // 2],
        "answer_tokens_max": ans[-1],
    }
