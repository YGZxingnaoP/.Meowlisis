# -*- coding: utf-8 -*-
"""双流调度：思考流与输出流并行推进，由思考流决定输出要不要停。

一轮的结构（论文 §3.2 + 附录 B）
-------------------------------
    reset(messages)  填 P（一次 prefill）→ 给 T / W 写各自的前缀 → 填探针提示词 M
    step()           两条流各出一个 token（一次前向），到点就问一次
                       "are my current thoughts enough to write the next paragraph?"

论文的四条规则与落点
-------------------
1. **并行**：同一个 step 里 thinker / writer 各取一个 token（`_forward_pair` 一次前向）。
2. **探针**：每 `probe_every` 个 decode step，或思考流出现 `\\n\\n`（段末），用独立视图
   `M -> T -> W -> Q` 判一次 yes/no（`_probe`）；判完把 Q 清空，问句不进思维链。
3. **判定**：p(yes) > p(no) → 允许 writer 写；否则**不放行**（不再把半句话冻住，
   见 `_switching` 里的说明：8B 在句子中间冻结后会一路答 no）。`yes_bias` 就是论文
   Figure 4 的 "+Δ"。
4. **让位**：writer 自己走到 `\\n\\n`（段落边界）时先停一下，等下一次 yes 再写
   （附录 B：prevents the writer from getting too far ahead）；思考流输出 `</think>`
   时切成 writer-only，让 writer 把回复写完。

旧实现错在哪（留个记号，别再走回去）
---------------------------------
* 旧版只在 writer **已经停下**时才探针，pause 由 `writer_max` 这个固定 token 数触发，
  不是由思考判定触发 —— 那是"分段写"，不是论文。
* 旧版恢复时往 writer 流里塞 `<|im_end|>\\n<|im_start|>assistant\\n`，模型看到的是
  "上一轮结束了"，于是复述；论文是连续续写，什么都不塞。
* 旧版在思考结束（或连续两次 no）时把 writer 一起判死，回复被腰斩。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import torch

from meowllm.engine.dualstream.attention import ARContext, attach
from meowllm.engine.dualstream.blocks import Block, BlockCache, BlockLayout, View
from meowllm.engine.dualstream.mode import ModeController, ModeDecision
from meowllm.engine.dualstream.prompts import (MODE_SWITCHING_PROMPT,
                                               THINKER_OUTPUT_PREFIX,
                                               WRITER_OUTPUT_PREFIX, render_chat)
from meowllm.engine.dualstream.rope import DeltaRotator

#: 思考流的自然结束标记（Qwen3 想完会写 </think>）
THINKER_STOP_MARKS = ("</think>",)

#: 输出流的额外结束标记：多轮聊天里常见的"越界开头"，命中就收尾
WRITER_STOP_MARKS = ("\n用户：", "\n主人：", "\n用户:", "\nHuman:", "</think>")

#: 段落分隔：写作流走到这里让位，思考流走到这里顺手问一次
PARAGRAPH = "\n\n"


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
    #: writer 被冻结的次数（含段落让位）
    pauses: int = 0
    #: 冻结后重新放行的次数
    resumes: int = 0
    #: 探针次数 / 判 no 的次数
    probes: int = 0
    probe_no: int = 0
    last_probe_p_yes: float = 0.0
    last_probe_p_no: float = 0.0
    #: 思考领先输出多少个 token（正数 = 思考跑在前面）
    thinker_ahead: int = 0
    #: 两种暂停原因各多少次（观测用）
    pause_thoughts: int = 0
    pause_paragraph: int = 0
    #: 保险丝生效次数（`stall_guard_tokens>0` 才有）
    forced_resumes: int = 0


class DualStreamLoop:
    """持有模型状态的调度器。一个请求一个实例。"""

    def __init__(self, model, tokenizer, thinker_max: int = 256,
                 writer_max: int = 192, probe_every: int = 20,
                 device: str = "cuda", temperature: float = 0.8,
                 top_p: float = 0.9, seed: int | None = None,
                 prompt_capacity: int = 8192, pause_on_paragraph: bool = True,
                 yes_bias: float = 0.0, stall_guard_tokens: int = 0,
                 fast_prefill: bool = True) -> None:
        self.model = model
        self.tok = tokenizer
        self.device = device
        self.thinker_max = max(1, int(thinker_max))
        #: writer 的**总**预算（不是每段），到顶就按 length 收尾
        self.writer_max = max(1, int(writer_max))
        self.prompt_capacity = max(1024, int(prompt_capacity))
        self.pause_on_paragraph = bool(pause_on_paragraph)
        #: 论文没有的保险丝：冻结超过这么多思考 token 仍等不到 yes，就强制放行一次
        #: （0 = 关，保持论文原样。论文把这个失败形态叫 stalling。）
        self.stall_guard_tokens = max(0, int(stall_guard_tokens))
        self.temperature = temperature
        self.top_p = top_p
        self.seed = seed

        self.layout = BlockLayout()
        self.rotator = DeltaRotator(model)
        self.ctx = ARContext(layout=self.layout, rotator=self.rotator,
                             fast_prefill=bool(fast_prefill))
        #: 把上下文挂到所有 attention 模块，并让模型改用我们的实现
        self.attached_layers = attach(model, self.ctx)
        self.mode = ModeController(tokenizer, probe_every, yes_bias=yes_bias)

        # 两条流的前缀与探针提示词（官方逐字）
        self.thinker_prefix = self._encode(THINKER_OUTPUT_PREFIX)
        self.writer_prefix = self._encode(WRITER_OUTPUT_PREFIX)
        self.mode_prompt = self._encode(MODE_SWITCHING_PROMPT)

        # 结束标记的 token id：命中就停，且**不**把它吐出去。
        # 只靠字符串后缀判断不够，`<|im_end|>` 这类特殊 token 会先解码成文本再发出去。
        self._stop_ids: set[int] = set()
        for tid in (getattr(tokenizer, "eos_token_id", None),
                    *tokenizer.encode("<|im_end|>", add_special_tokens=False),
                    *tokenizer.encode("<|endoftext|>", add_special_tokens=False),
                    *tokenizer.encode("</think>", add_special_tokens=False)):
            if isinstance(tid, int):
                self._stop_ids.add(tid)

        #: token -> 文本的增量解码缓冲（thinker / writer 各一份，见 _decode）
        self._dec_buf: dict[str, dict] = {}
        self.cache = BlockCache(self.layout, view=View.WRITER,
                                target_block=Block.PROMPT)
        self._generator: torch.Generator | None = None
        self.debug_hook = None

        self.prompt_ids: list[int] = []
        self.prompt_tokens = 0
        self._reset_state()

    # ------------------------------------------------------------------ 基础
    def _reset_state(self) -> None:
        self.cache = BlockCache(self.layout, view=View.WRITER,
                                target_block=Block.PROMPT)
        self.thinker_ids: list[int] = []
        self.writer_ids: list[int] = []
        self.thinker_logits: torch.Tensor | None = None
        self.writer_logits: torch.Tensor | None = None
        #: 写作流能不能推进（论文里的"暂停 / 继续写作"）
        self.writer_active = False
        self.thinker_done = False
        self.writer_done = False
        self.thinker_stop = ""
        #: "stop" | "length"（被 writer 预算截断）
        self.finish_reason = "stop"
        self.pause_reason = ""
        #: 冻结发生在第几个 step（保险丝用）
        self._paused_at = 0
        self.steps = 0
        self._thinker_buf = ""
        self._writer_buf = ""
        self._dec_buf.clear()
        self.stats = LoopStats()

    def _encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return list(self.tok.encode(text, add_special_tokens=add_special_tokens))

    def _new_generator(self) -> torch.Generator | None:
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
        self.ctx.rows = None
        self.cache.view = view
        self.cache.target_block = block
        self.cache.rows = None

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

        # 对拍钩子：此刻的 token 列表与该 forward 看到的上下文完全一致。
        if self.debug_hook is not None:
            self.debug_hook(block, view, logits,
                            list(self.prompt_ids), list(self.thinker_ids),
                            list(self.writer_ids), count)
        return logits

    def _sample(self, logits: torch.Tensor) -> int:
        """温度 + top-p 采样；temperature<=0 时退化为贪心。"""
        if self.temperature <= 0:
            return int(torch.argmax(logits).item())
        probs = torch.softmax(logits / max(self.temperature, 1e-5), dim=-1)
        if 0 < self.top_p < 1.0:
            sorted_probs, sorted_idx = torch.sort(probs, descending=True)
            cumulative = torch.cumsum(sorted_probs, dim=-1)
            over = (cumulative > self.top_p).nonzero()
            cut = int(over[0].item()) + 1 if len(over) else len(sorted_probs)
            keep = sorted_idx[:cut]
            masked = torch.zeros_like(probs).scatter(0, keep, probs[keep])
            probs = masked / masked.sum()
        return int(torch.multinomial(probs, 1, generator=self._generator).item())

    def _decode(self, token_id: int, stream: str = "writer") -> str:
        """**按累积 id 解码，不要单 token 解**。

        中文一个字符经常横跨 2~3 个字节级 BPE token。`decode([id])` 单独解一个
        不完整的 token，transformers 只能吐 U+FFFD（`�`）。这里把 id 攒起来整体解，
        遇到"解出来还剩半个字"（末尾是 U+FFFD）就先不吐，等下一个 token 补齐。

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

    # ------------------------------------------------------------------ 启动
    def reset(self, messages: list[dict]) -> None:
        """建上下文：P（共享）+ T/W 各自的前缀 + 探针提示词 M。"""
        self.prompt_ids = self._encode(render_chat(list(messages)))
        need = len(self.prompt_ids) + 8
        if need > self.prompt_capacity:
            raise RuntimeError(
                f"prompt {len(self.prompt_ids)} token 超过上限 "
                f"{self.prompt_capacity}，请调大 context.n_ctx")

        self.layout = BlockLayout()
        self.layout.capacity[Block.PROMPT] = min(
            self.prompt_capacity, max(64, ((need + 63) // 64) * 64))
        self.layout.capacity[Block.THINKER] = max(64, self.thinker_max + 64)
        self.layout.capacity[Block.WRITER] = max(64, self.writer_max + 64)
        self.layout.capacity[Block.MODE] = max(64, len(self.mode_prompt) + 8)
        self.layout.capacity[Block.QUESTION] = max(32, len(self.mode.question_ids) + 8)
        self.rotator = DeltaRotator(self.model)
        self.ctx.layout = self.layout
        self._reset_state()
        self.prompt_tokens = len(self.prompt_ids)
        self._generator = self._new_generator()

        # P 只 prefill 一次，三个视图共享
        self._forward(self.prompt_ids, Block.PROMPT, View.WRITER)
        # 两条流各自的前缀（= 论文的 linker）
        self.thinker_logits = self._forward(self.thinker_prefix, Block.THINKER,
                                            View.THINKER)
        self.writer_logits = self._forward(self.writer_prefix, Block.WRITER,
                                           View.WRITER)
        # 探针的固定提示词：只填一次，之后每轮只重写问句 Q
        if self.mode_prompt:
            self._forward(self.mode_prompt, Block.MODE, View.MODE)
        # 论文：writer 一开始就写，不用等思考
        self.writer_active = True

    # ------------------------------------------------------------------ 推进
    def step(self) -> list[StreamChunk]:
        """两条流各推进一个 token，然后做一次模式切换判定。"""
        chunks: list[StreamChunk] = []
        tok_t: int | None = None
        tok_w: int | None = None

        # ---- 1. 按当前 logits 各取一个 token ----
        if not self.thinker_done and self.thinker_logits is not None:
            if self.stats.thinker_tokens >= self.thinker_max:
                self.thinker_done = True
                self.thinker_stop = "max_tokens"
            else:
                token = self._sample(self.thinker_logits)
                if token in self._stop_ids:
                    self.thinker_done = True
                    self.thinker_stop = "stop_token"
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

        if not self.writer_done and self.writer_active and self.writer_logits is not None:
            if self.stats.writer_tokens >= self.writer_max:
                self.writer_done = True
                self.finish_reason = "length"
            else:
                logits = self.writer_logits
                if self.stats.writer_tokens == 0:
                    # 第一个字不许直接收尾：0.6B 在"该先想"的问题上第一个 token 有
                    # p=0.71 落在 </think>/<|endoftext|>，整条回复会变成空的。
                    # 只挡第一个 token，之后照常（中途收尾是合法的）。
                    logits = logits.clone()
                    logits[list(self._stop_ids)] = float("-inf")
                token = self._sample(logits)
                if token in self._stop_ids:
                    self.writer_done = True        # 自然收尾：回复写完了
                else:
                    text = self._decode(token, "writer")
                    self.writer_ids.append(token)
                    self.stats.writer_tokens += 1
                    self._writer_buf += text
                    chunks.append(StreamChunk("writer", text, token))
                    tok_w = token
                    if any(mark in self._writer_buf for mark in WRITER_STOP_MARKS):
                        self.writer_done = True

        # ---- 2. 一次前向把两条流的新 token 写进 KV（论文 Figure 3）----
        if tok_t is not None and tok_w is not None:
            self.thinker_logits, self.writer_logits = self._forward_pair(tok_t, tok_w)
        elif tok_t is not None:
            self.thinker_logits = self._forward([tok_t], Block.THINKER, View.THINKER)
        elif tok_w is not None:
            self.writer_logits = self._forward([tok_w], Block.WRITER, View.WRITER)

        self.steps += 1

        # ---- 3. 模式切换（问句看得到本步刚写进去的 token）----
        self._switching(chunks, tok_t, tok_w)
        self.stats.thinker_ahead = (self.stats.thinker_tokens
                                    - self.stats.writer_tokens)
        return chunks

    def _forward_pair(self, tok_t: int, tok_w: int):
        """一次前向同时推进 thinker 与 writer 两行。"""
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

        try:
            with torch.no_grad():
                out = self.model(input_ids=ids, position_ids=pos,
                                 past_key_values=self.cache, use_cache=True)
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

    def _switching(self, chunks: list[StreamChunk],
                   tok_t: int | None, tok_w: int | None) -> None:
        """论文 §3.2 的模式切换：何时停、何时继续。"""
        # 思考结束 → writer-only（论文："让 writer 把回复写完"）
        if self.thinker_done:
            if not self.writer_done and not self.writer_active:
                self.writer_active = True
                self.pause_reason = ""
                self.stats.resumes += 1
            return
        if self.writer_done:
            return

        # 写作流自己走到段落边界 → 先停，等新的想法（附录 B 最后一句）
        if (self.pause_on_paragraph and tok_w is not None
                and self._writer_buf.endswith(PARAGRAPH)):
            self._pause("paragraph")

        # 到点就问：每 probe_every 个 step，或思考流出现段末
        thinker_para = tok_t is not None and self._thinker_buf.endswith(PARAGRAPH)
        due = self.mode.tick()
        if not (due or thinker_para):
            return
        self.mode.reset_counter()

        # 可选保险丝（论文没有，默认关）：冻结太久等不到 yes，就先放它说一段。
        # 论文把这种"提前说"当失败形态，只在 p(yes) 长期压不过 p(no) 时才需要它。
        if (not self.writer_active and self.stall_guard_tokens > 0
                and self.steps - self._paused_at >= self.stall_guard_tokens):
            self._force_resume()
            return

        decision: ModeDecision = self._probe()
        self.stats.probes += 1
        self.stats.last_probe_p_yes = decision.p_yes
        self.stats.last_probe_p_no = decision.p_no
        chunks.append(StreamChunk("mode", "", None, {
            "event": "probe",
            "continue_speaking": decision.continue_speaking,
            "p_yes": decision.p_yes,
            "p_no": decision.p_no,
            "note": decision.note,
        }))

        if decision.continue_speaking:
            if not self.writer_active:
                self.writer_active = True
                self.pause_reason = ""
                self.stats.resumes += 1
        else:
            self.stats.probe_no += 1
            # 论文是"no 就立刻冻结 writer"。实测（Qwen3-8B）在**句子中间**冻结之后，
            # 探针会连续答 no（p(no)=0.73，12 次全 no）：它看到的是半句话，
            # "够不够写下一段"永远不成立，writer 就再也放行不了 —— 只剩"一轮叫停"。
            # 所以 no 只表示"先别开下一段"：writer 把当前这段写完，到空行自然冻结
            # （段落让位本来就是论文的规则），于是每次判定都发生在段边界上。
            if not self.writer_active:
                self.pause_reason = self.pause_reason or "thoughts"

    def _pause(self, reason: str) -> None:
        """冻结 writer，并把探针计数清零（停过之后重新数 `probe_every` 步）。"""
        if self.writer_active:
            self.stats.pauses += 1
            if reason == "paragraph":
                self.stats.pause_paragraph += 1
            else:
                self.stats.pause_thoughts += 1
            self._paused_at = self.steps
        self.writer_active = False
        self.pause_reason = reason
        self.mode.reset_counter()

    def _force_resume(self) -> None:
        """保险丝放行：不算探针，也不改 note。"""
        if self.writer_active:
            return
        self.writer_active = True
        self.pause_reason = ""
        self.stats.resumes += 1
        self.stats.forced_resumes += 1

    def _probe(self) -> ModeDecision:
        """论文附录 B 的第三视图：M -> T -> W -> Q，读完立刻清空 Q。"""
        self.layout.set_len(Block.QUESTION, 0)
        logits = None
        if self.mode.question_ids:
            logits = self._forward(self.mode.question_ids, Block.QUESTION, View.MODE)
        self.layout.set_len(Block.QUESTION, 0)     # 问句不出现在任何视图里
        if logits is None:
            return ModeDecision(True, 0.0, 0.0, "问句为空，保守继续")
        return self.mode.decide(logits)

    # ------------------------------------------------------------------ 状态
    @property
    def finished(self) -> bool:
        """writer 收尾就结束：回答写完了，再推思考既看不见也没意义。"""
        return self.writer_done

    @property
    def thinker_text(self) -> str:
        return self._thinker_buf

    @property
    def writer_text(self) -> str:
        return self._writer_buf

    def blocks(self) -> dict:
        """当前五块内容（给参考实现/对拍用）。"""
        return {
            Block.PROMPT: list(self.prompt_ids),
            Block.THINKER: list(self.thinker_ids),
            Block.WRITER: list(self.writer_ids),
            Block.MODE: list(self.mode_prompt),
            Block.QUESTION: [],
        }
