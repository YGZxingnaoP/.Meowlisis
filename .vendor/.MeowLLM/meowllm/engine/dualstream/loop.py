# -*- coding: utf-8 -*-
"""双流调度：思考流与输出流各自推进。

一轮的结构
----------
    reset(messages)  建 P 块（一次 prefill）
    reset() 末尾     给 T / W 各写入角色起始标记
    step()           各推进一个 token；思考到间隔就插探针判定要不要暂停 Writer
    finished         两流都自然结束

关键性质（对应论文的三条）
--------------------------
1. 输出开始时思考没停 —— 两条流在同一 `step()` 里各取一个 token
2. 思考停了输出还能继续 —— Thinker 结束后 Writer 继续单独推进
3. 两流寿命互不绑定 —— 各自有独立的结束条件

v1 有意简化（写在这里避免误读）
-------------------------------
* 用「块内起始标记」代替论文的 linker 块：Writer 块以 `我说：` 开头，
  Thinker 块以 `<think>` 开头。作用相同（告诉模型这段是谁在写），实现更简单。
* 探针判定后把 T 块 **截断回原长度** 来实现"隐藏探针 KV"，而不是在注意力里
  跳过若干 KV 条目。效果等价，代价是探针那几个 token 白算一次。
* 每步两个视图各做一次 forward，没有合并成一个 batch。合并留给优化版。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import torch

from meowllm.engine.dualstream.attention import ARContext, attach
from meowllm.engine.dualstream.blocks import Block, BlockCache, BlockLayout, View
from meowllm.engine.dualstream.mode import ModeController
from meowllm.engine.dualstream.prompts import pick
from meowllm.engine.dualstream.rope import DeltaRotator

#: 角色起始标记由 prompts.py 的 thinker_mark / writer_mark 提供（即论文的 linker 文本）。
#: 这里不再自造"我说：/<think>"这类标记 —— 那是与论文的偏差。

#: 自然结束信号
THINKER_STOP_MARKS = ("</think>",)
WRITER_STOP_MARKS = ("\n用户：", "\n主人：", "\n用户:", "\nHuman:", "</think>")


@dataclass
class StreamChunk:
    """一条流产出的一小段。`stream` 取 "thinker" / "writer" / "mode"。"""

    stream: str
    text: str
    token_id: int | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class LoopStats:
    """给 /control/stats 用的观测值。"""

    writer_tokens: int = 0
    thinker_tokens: int = 0
    pauses: int = 0
    resumes: int = 0
    probes: int = 0
    segments: int = 0
    probe_no: int = 0
    last_probe_p_yes: float = 0.0
    #: 思考领先输出多少个 token（正数 = 思考跑在前面）
    thinker_ahead: int = 0
    #: 每一步的 wall clock（毫秒），最近 16 步
    recent_step_ms: list = field(default_factory=list)


class DualStreamLoop:
    """持有模型状态的调度器。一个会话一个实例。"""

    def __init__(self, model, tokenizer, language: str = "zh",
                 thinker_max: int = 256, writer_max: int = 192,
                 probe_every: int = 20, device: str = "cuda",
                 temperature: float = 0.8, top_p: float = 0.9,
                 seed: int | None = None, prompt_capacity: int = 8192,
                 max_segments: int = 6, stop_after_no: int = 2,
                 probe_kind: str = "roleplay", fast_prefill: bool = True) -> None:
        self.model = model
        self.tok = tokenizer
        #: token -> 文本的增量解码缓冲（thinker / writer 各一份，见 _decode）
        self._dec_buf: dict[str, dict] = {}
        self.language = language
        self.device = device
        self.thinker_max = thinker_max
        self.writer_max = writer_max
        self.prompt_capacity = max(1024, int(prompt_capacity))
        self.max_segments = max(1, int(max_segments))
        self.stop_after_no = max(1, int(stop_after_no))
        self.temperature = temperature
        self.top_p = top_p
        self.seed = seed

        self.layout = BlockLayout()
        self.rotator = DeltaRotator(model)
        self.ctx = ARContext(layout=self.layout, rotator=self.rotator,
                             fast_prefill=bool(fast_prefill))
        #: 把上下文挂到所有 attention 模块，并让模型改用我们的实现
        self.attached_layers = attach(model, self.ctx)
        self.mode = ModeController(tokenizer, language, probe_every,
                                   probe_kind=probe_kind)
        self.marks = pick(language)

        # 结束标记的 token id：命中就停，且**不**把它吐出去。
        # 只靠字符串后缀判断不够，因为 `<|im_end|>` 这类特殊 token 会先解码成文本
        # 再被我们当成正文发出去（实测泄漏过 `</think>` 与 `Human:` 后续对话）。
        self._stop_ids: set[int] = set()
        for tid in (getattr(tokenizer, "eos_token_id", None),
                    *tokenizer.encode("<|im_end|>", add_special_tokens=False),
                    *tokenizer.encode("<|endoftext|>", add_special_tokens=False),
                    *tokenizer.encode("</think>", add_special_tokens=False)):
            if isinstance(tid, int):
                self._stop_ids.add(tid)

        self.boundary_text = "<|im_end|>\n<|im_start|>assistant\n"
        self._boundary_ids: list[int] = list(
            tokenizer.encode(self.boundary_text, add_special_tokens=False))
        self._segment_start_mask: set[int] = set(self._stop_ids)
        for text in ("<think>", "<|im_start|>", "<|im_start|>assistant"):
            try:
                ids = tokenizer.encode(text, add_special_tokens=False)
            except Exception:
                ids = []
            if len(ids) == 1:
                self._segment_start_mask.add(int(ids[0]))

        self.cache = self._new_cache()
        self.prompt_ids: list[int] = []
        self.thinker_prefix: list[int] = []
        self.writer_prefix: list[int] = []
        self.thinker_ids: list[int] = []
        self.writer_ids: list[int] = []
        self.thinker_logits: torch.Tensor | None = None
        self.writer_logits: torch.Tensor | None = None
        self.thinker_done = False
        self.writer_done = False
        self.writer_paused = False
        self.segments = 0
        self.consecutive_no = 0
        self._segment_writer_tokens = 0
        self.thinker_stop = ""
        self.segment_texts: list[str] = []
        self._segment_text_start = 0
        self.probing_stopped = False
        self.stats = LoopStats()
        self._thinker_buf = ""
        self._writer_buf = ""
        #: 调试钩子：每次 _forward 产出 logits 后回调，签名
        #: (block, view, logits, prompt_ids, thinker_ids, writer_ids, token_count)
        #: 仅供对拍脚本使用；正常运行时为 None，零开销。
        self.debug_hook = None

    # ------------------------------------------------------------------ 基础
    def _new_cache(self) -> BlockCache:
        return BlockCache(self.layout, view=View.WRITER,
                          target_block=Block.PROMPT)

    def _gen(self) -> torch.Generator | None:
        if self.seed is None:
            return None
        gen = torch.Generator(device=self.device)
        gen.manual_seed(int(self.seed))
        return gen

    def _forward(self, token_ids: list[int], block: Block, view: View) -> torch.Tensor:
        """把 token 追加进指定块，返回"下一个 token"的 logits，形状 (vocab,)。

        顺序很关键：
        1. 先按"块内相对位置"算好 position_ids（存储位置）。
        2. **前移**布局，让 attention 能按新长度切块。
        3. 用 `cache.pending` 告诉 cache"这些 token 还在途"，
           使 `get_seq_length()` 仍返回前移前的长度，cache_position 才不会错。
        """
        self.ctx.view = view
        self.ctx.own_block = block
        self.cache.view = view
        self.cache.target_block = block

        start = self.layout.lengths[block]
        count = len(token_ids)
        self.layout.set_len(block, start + count)     # ② 先前移
        self.cache.pending = count                    # ③ 在途标记

        ids = torch.tensor([token_ids], dtype=torch.long, device=self.device)
        positions = torch.arange(start, start + count,
                                 dtype=torch.long, device=self.device).unsqueeze(0)
        try:
            with torch.no_grad():
                out = self.model(input_ids=ids, position_ids=positions,
                                 past_key_values=self.cache, use_cache=True)
        finally:
            self.cache.pending = 0
        logits = out.logits[0, -1].float()

        # 对拍钩子：此刻的 token 列表与该 forward 看到的上下文完全一致，
        # 所以参考实现可以在这个点上做等价比较。
        if self.debug_hook is not None:
            self.debug_hook(block, view, logits,
                            list(self.prompt_ids), list(self.thinker_ids),
                            list(self.writer_ids), count)
        return logits

    def _sample(self, logits: torch.Tensor) -> int:
        """温度 + top-p 采样；temperature<=0 时退化为贪心。"""
        if self.temperature <= 0:
            return int(torch.argmax(logits).item())
        scaled = logits / max(self.temperature, 1e-5)
        probs = torch.softmax(scaled, dim=-1)
        if 0 < self.top_p < 1.0:
            sorted_probs, sorted_idx = torch.sort(probs, descending=True)
            cumulative = torch.cumsum(sorted_probs, dim=-1)
            over = (cumulative > self.top_p).nonzero()
            cut = int(over[0].item()) + 1 if len(over) else len(sorted_probs)
            keep = sorted_idx[:cut]
            masked = torch.zeros_like(probs).scatter(0, keep, probs[keep])
            probs = masked / masked.sum()
        return int(torch.multinomial(probs, 1, generator=self._gen()).item())

    def _encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return list(self.tok.encode(text, add_special_tokens=add_special_tokens))

    def _decode(self, token_id: int, stream: str = "writer") -> str:
        """**按累积 id 解码，不要单 token 解**。

        中文一个字符经常横跨 2~3 个字节级 BPE token。`decode([id])` 单独解一个
        不完整的 token，transformers 只能吐 U+FFFD（`�`）—— 实测"推荐"会变成
        "�荐"、"比如"变成"�如"。这里把 id 攒起来整体解，遇到"解出来还剩半个字"
        （末尾是 U+FFFD）就先不吐，等下一个 token 补齐；补齐后再一次性给出。

        thinker / writer 是两条独立文本流，各用各的缓冲（stream 参数）。
        """
        buf = self._dec_buf.setdefault(stream, {"ids": [], "n": 0})
        buf["ids"].append(int(token_id))
        text = self.tok.decode(buf["ids"], skip_special_tokens=True)
        if text.endswith("\ufffd"):
            # 末尾是半个多字节字符：不推进已发长度，等下一个 token
            return ""
        delta = text[buf["n"]:]
        buf["n"] = len(text)
        return delta

    def _reset_decoder(self, stream: str | None = None) -> None:
        """换一段独立文本前清一次（stream=None 清全部）。"""
        if stream is None:
            self._dec_buf.clear()
        else:
            self._dec_buf.pop(stream, None)

    # ------------------------------------------------------------------ 启动
    def reset(self, messages: list[dict]) -> None:
        """严格按论文 Figure 2 建立两个视图。

        论文布局（每个视图有独立的 Prompt Block 与独立的 linker）：

            writer 视图:  PROMPT_W -> THINKER -> LINK_W -> WRITER
            thinker 视图: PROMPT_T -> WRITER  -> LINK_T -> THINKER

        Prompt Block 里放"该角色的 system 说明 + 用户任务"；linker 放论文那两句
        `SYSTEM: [...]` 哨兵，用来告诉模型"接下来该谁写"。
        """
        marks = self.marks
        # 官方实现：**共享一份 prompt**（没有 system），两视图看同一份。
        # 多轮：把完整历史渲染进去（不再只取最后一条 user 消息）。
        from meowllm.engine.dualstream.prompts import render_chat

        self.prompt_ids = self._encode(render_chat(list(messages)),
                                      add_special_tokens=False)
        # 两条流的开头文本（官方逐字）：writer 的那段就是论文的 linker
        self.thinker_prefix = self._encode(marks["thinker_output_prefix"],
                                          add_special_tokens=False)
        self.writer_prefix = self._encode(marks["writer_output_prefix"],
                                         add_special_tokens=False)

        self.layout = BlockLayout()
        need = len(self.prompt_ids) + 8
        if need > self.prompt_capacity:
            raise RuntimeError(
                f"prompt {len(self.prompt_ids)} token 超过上限 "
                f"{self.prompt_capacity}，请调大 context.n_ctx")
        self.layout.capacity[Block.PROMPT] = min(
            self.prompt_capacity, max(64, ((need + 63) // 64) * 64))
        self.layout.capacity[Block.THINKER] = max(64, self.thinker_max + 64)
        self.layout.capacity[Block.WRITER] = max(
            64, self.writer_max * self.max_segments + 8 * (self.max_segments + 1))
        self.rotator = DeltaRotator(self.model)
        self.ctx.layout = self.layout
        self.cache = self._new_cache()
        self.thinker_ids, self.writer_ids = [], []
        self.thinker_done = self.writer_done = False
        self.writer_paused = True
        self._writer_started = False
        self.writer_logits = None
        self.segments = 0
        self.consecutive_no = 0
        self._segment_writer_tokens = 0
        self.thinker_stop = ""
        self._reset_decoder()          # 新请求：两条流都从干净缓冲开始
        self.segment_texts: list[str] = []
        self._segment_text_start = 0
        self.probing_stopped = False
        self.prompt_tokens = len(self.prompt_ids)
        self.stats = LoopStats()
        self._thinker_buf = self._writer_buf = ""

        self._forward(self.prompt_ids, Block.PROMPT, View.WRITER)

        self.thinker_logits = self._forward(
            self.thinker_prefix, Block.THINKER, View.THINKER)
        self._start_writer()

    def _start_writer(self) -> None:
        if self._writer_started:
            return
        self._writer_started = True
        self.writer_paused = False
        self._segment_writer_tokens = 0
        self.writer_logits = self._forward(
            self.writer_prefix, Block.WRITER, View.WRITER)

    def _resume_writer(self) -> None:
        if self.writer_done or self._boundary_ids is None:
            return
        self.writer_logits = self._forward(
            self._boundary_ids, Block.WRITER, View.WRITER)
        self.writer_paused = False
        self._segment_writer_tokens = 0
        self.consecutive_no = 0
        self.mode.reset_counter()
        self.stats.resumes += 1

    def _end_segment(self) -> None:
        self.segments += 1
        self.stats.segments = self.segments
        self._segment_writer_tokens = 0
        self.consecutive_no = 0
        self.mode.reset_counter()
        if self.segments >= self.max_segments:
            self.writer_done = True
            self.thinker_done = True
            self.thinker_stop = self.thinker_stop or "max_segments"
            return
        self.writer_paused = True
        self.stats.pauses += 1

    def _close_segment(self, chunks: list) -> None:
        self._end_segment()
        text = self._writer_buf[self._segment_text_start:]
        if text.strip():
            self.segment_texts.append(text)
        self._segment_text_start = len(self._writer_buf)
        chunks.append(StreamChunk("mode", "", None, {
            "event": "segment_end",
            "segments": self.segments,
            "paused": self.writer_paused,
        }))

    def blocks(self) -> dict:
        """当前三块内容（给参考实现/对拍用）。"""
        return {
            Block.PROMPT: list(self.prompt_ids),
            Block.THINKER: list(self.thinker_ids),
            Block.WRITER: list(self.writer_ids),
        }

    # ------------------------------------------------------------------ 推进
    def step(self) -> list[StreamChunk]:
        """两条流各推进一个 token，返回本步事件。"""
        chunks: list[StreamChunk] = []
        tok_t: int | None = None
        tok_w: int | None = None

        # ---- Thinker ----
        if not self.thinker_done and self.thinker_logits is not None:
            if len(self.thinker_ids) >= self.thinker_max:
                self.thinker_done = True
                self.thinker_stop = "max_tokens"
            else:
                logits = self.thinker_logits
                if self.writer_paused and not self.probing_stopped:
                    logits = logits.clone()
                    logits[list(self._stop_ids)] = float("-inf")
                token = self._sample(logits)
                if token in self._stop_ids:
                    self.thinker_done = True
                    self.thinker_stop = "stop_token:%d" % int(token)
                else:
                    text = self._decode(token, "thinker")
                    self.thinker_ids.append(token)
                    self.stats.thinker_tokens += 1
                    self._thinker_buf += text
                    chunks.append(StreamChunk("thinker", text, token))
                    tok_t = token
                    if any(mark in self._thinker_buf for mark in THINKER_STOP_MARKS):
                        self.thinker_done = True
                        self.thinker_stop = "think_mark"

        if self.thinker_done and self.writer_paused:
            self.writer_done = True
            self.thinker_stop = self.thinker_stop or "writer_paused"

        if (not self.thinker_done and self.writer_paused
                and self._writer_started and not self.probing_stopped
                and not self.writer_done and self.mode.tick(1)):
            decision = self._probe()
            chunks.append(StreamChunk("mode", "", None, {
                "event": "probe",
                "continue_speaking": decision.continue_speaking,
                "p_yes": decision.p_yes,
                "p_no": decision.p_no,
                "note": decision.note,
            }))
            if decision.continue_speaking:
                self._resume_writer()
            else:
                self.consecutive_no += 1
                self.stats.probe_no += 1
                if self.consecutive_no >= self.stop_after_no:
                    self.probing_stopped = True

        if (not self.writer_done and not self.writer_paused
                and self.writer_logits is not None):
            if self._segment_writer_tokens >= self.writer_max:
                self._close_segment(chunks)
            else:
                logits = self.writer_logits
                if self._segment_writer_tokens == 0:
                    logits = logits.clone()
                    logits[list(self._segment_start_mask)] = float("-inf")
                token = self._sample(logits)
                if token in self._stop_ids:
                    self._close_segment(chunks)
                else:
                    text = self._decode(token, "writer")
                    self.writer_ids.append(token)
                    self.stats.writer_tokens += 1
                    self._segment_writer_tokens += 1
                    self._writer_buf += text
                    chunks.append(StreamChunk("writer", text, token))
                    tok_w = token
                    if any(mark in self._writer_buf for mark in WRITER_STOP_MARKS):
                        self._close_segment(chunks)

        # ---- 一次前向同时推进两条流（论文 Figure 3 的 batched inference）----
        # 动机（实测）：这台机器上单次前向有 ~31 ms 的固定开销，
        # batch=4 与 batch=8 同价，所以两行并一行几乎是白拿。
        if tok_t is not None and tok_w is not None:
            self.thinker_logits, self.writer_logits = self._forward_pair(tok_t, tok_w)
        elif tok_t is not None:
            self.thinker_logits = self._forward([tok_t], Block.THINKER, View.THINKER)
        elif tok_w is not None:
            self.writer_logits = self._forward([tok_w], Block.WRITER, View.WRITER)

        self.stats.thinker_ahead = (self.stats.thinker_tokens
                                    - self.stats.writer_tokens)
        return chunks

    def _forward_pair(self, tok_t: int, tok_w: int):
        """一次前向同时推进 thinker 与 writer 两行（支持 CUDA Graph 重放）。"""
        t_before = self.layout.lengths[Block.THINKER]
        w_before = self.layout.lengths[Block.WRITER]
        self.layout.add(Block.THINKER, 1)
        self.layout.add(Block.WRITER, 1)

        rows = [(View.THINKER, Block.THINKER), (View.WRITER, Block.WRITER)]
        self.cache.target_blocks = [Block.THINKER, Block.WRITER]
        self.cache.rows = rows
        self.cache.pending = 1
        self.cache.view = View.THINKER
        self.ctx.rows = rows
        self.ctx.layout = self.layout
        self.ctx.view = View.THINKER
        self.ctx.own_block = Block.THINKER

        ids = torch.tensor([[tok_t], [tok_w]], device=self.device, dtype=torch.long)
        pos = torch.tensor([[t_before], [w_before]], device=self.device, dtype=torch.long)

        def run():
            return self.model(input_ids=ids, position_ids=pos,
                              past_key_values=self.cache, use_cache=True)

        try:
            with torch.no_grad():
                out = run()
            logits = out.logits[:, -1, :].float()
            if self.debug_hook is not None and logits.shape[0] == 2:
                self.debug_hook(Block.WRITER, View.WRITER, logits[1],
                                self.prompt_ids, self.thinker_ids,
                                self.writer_ids, 1)
        finally:
            self.cache.pending = 0
            self.cache.target_blocks = None
            self.cache.rows = None
            self.ctx.rows = None
        return logits[0], logits[1]

    def _probe(self):
        """插探针 → 判定 → 截断回原长度（等价于"隐藏探针 KV"）。"""
        before = self.layout.lengths[Block.THINKER]
        probe_ids = self._encode(self.mode.probe_text)
        if probe_ids:
            logits = self._forward(probe_ids, Block.THINKER, View.THINKER)
        else:
            logits = torch.zeros(1, device=self.device)
        decision = self.mode.decide(logits)
        # 隐藏探针：把 T 块截回插入前的长度，两个视图都不会再看到它
        self.cache.truncate(Block.THINKER, before)
        self.layout.set_len(Block.THINKER, before)
        self.stats.probes += 1
        self.stats.last_probe_p_yes = decision.p_yes
        return decision

    # ------------------------------------------------------------------ 状态
    @property
    def finished(self) -> bool:
        return self.writer_done and self.thinker_done

    @property
    def thinker_text(self) -> str:
        return self._thinker_buf

    @property
    def writer_text(self) -> str:
        return self._writer_buf

    def finger_print(self) -> str:
        """会话内容指纹，用于判断"有没有新的一轮"。"""
        blob = f"t:{len(self._thinker_buf)}|w:{len(self._writer_buf)}|{self.layout.total()}"
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]
