# -*- coding: utf-8 -*-
"""block 布局与角度表。

物理存储
--------
KV cache 里每个 token 只存一次，键按 **块内相对位置** 旋转：

    P 的第 i 个 token  -> 存储位置 i
    T 的第 j 个 token  -> 存储位置 j
    W 的第 k 个 token  -> 存储位置 k

视图中转
--------
两个视图只看顺序不同：

    Writer  视图:  P -> T -> W
    Thinker 视图:  P -> W -> T

各块在视图内的逻辑起点（blockStart）：

    Writer :  P=0,        T=p,          W=p+t
    Thinker:  P=0,        W=p,          T=p+w
    （p/t/w 分别是三块当前长度）

关键化简
--------
RoPE 的有效偏移只取决于 **查询被旋了多少** 与 **键被存时的旋转量**之差。
要让"视图中看到的相对距离"回到真实逻辑距离，查询需要额外旋转：

    delta(q块, k块, view) = blockStart(q块, view) - blockStart(k块, view)

这个 delta **只取决于两个块的编号和视图**，与具体第几个 token 无关 ——
所以可以预先算成一张 3x3 的表，每步直接查表，不需要逐 token 计算。
（论文按 query-key 对逐个写，落到实现就是这张常量表。）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import torch

try:  # transformers 5.x 的 Cache 基类
    from transformers import Cache
except Exception:  # pragma: no cover - 版本缺失时给个可诊断的替身
    Cache = object  # type: ignore[assignment,misc]


class Block(Enum):
    """三块 KV，严格对齐官方实现 `shared_cache_manager.py`。

    官方 `cache_structure` 长这样：

        [cache_prompt, cache_w2, cache_w1],   # A 看见：共享 prompt → 对方 → 自己
        [cache_prompt, cache_w1, cache_w2],   # B 看见：共享 prompt → 对方 → 自己

    注意 `cache_prompt` 在**两行里是同一个对象** —— 所以 Prompt Block 是**共享的一份**，
    不是每个视图各一份（Figure 2 的示意图与图注矛盾，以代码为准）。

    linker 也不是独立块：它是 writer 流的**开头文本**
    `" ... [SYSTEM: thoughts will continue here]\\n</think>\\n"`。
    """

    PROMPT = "P"        # 共享的 prompt 块（两视图同一份）
    THINKER = "T"       # 思考流（worker 0）
    WRITER = "W"        # 输出流（worker 1）


class View(Enum):
    """两种观察顺序。"""

    WRITER = "writer"
    THINKER = "thinker"


#: 每个视图里可见块的逻辑顺序：自己的 prompt → 对方 → 自己
VIEW_ORDER: dict[View, tuple[Block, Block, Block]] = {
    View.WRITER: (Block.PROMPT, Block.THINKER, Block.WRITER),
    View.THINKER: (Block.PROMPT, Block.WRITER, Block.THINKER),
}


@dataclass
class BlockLayout:
    """三块的当前长度，以及由长度推出的角度表。

    这是纯数据对象：不持张量、不认识 transformers。每次有 token 追加后
    调 `set_len` 让表失效即可。
    """

    lengths: dict[Block, int] = field(
        default_factory=lambda: {b: 0 for b in Block})
    #: 每块在物理缓冲里的**固定容量**（由 reset 时按上限设定）
    capacity: dict[Block, int] = field(
        default_factory=lambda: {b: 0 for b in Block})

    # ---------------------------------------------------------------- 长度
    def set_len(self, block: Block, value: int) -> None:
        """设置某块的当前长度（追加后调用）。"""
        self.lengths[block] = int(value)

    def add(self, block: Block, delta: int = 1) -> int:
        """给某块长度加 delta，返回新长度。"""
        self.lengths[block] += int(delta)
        return self.lengths[block]

    def total(self) -> int:
        """物理总长度（所有块之和，含当前视图不可见的块）。

        ⚠ 这个值**不能**拿去做 cache_position：它比"视图内可见长度"大。
        要看视图长度用 `view_total(view)`。
        """
        return sum(self.lengths.values())

    def view_total(self, view: View) -> int:
        """某视图内**可见**的 token 总数（= 该视图的逻辑序列长度）。"""
        return sum(self.lengths[b] for b in VIEW_ORDER[view])

    # ------------------------------------------------------------ 物理布局
    # 每块在缓冲里占据**固定容量**的一段，块的相对位置不随长度变化。
    # 这样写入是纯就地覆盖、读取是纯视图，生成期间**零分配** —— 才能上 CUDA Graph。
    def phys_start(self, block: Block) -> int:
        """某块在物理缓冲里的固定起点（= 前面所有块的容量之和）。"""
        offset = 0
        for b in PHYSICAL_ORDER:
            if b is block:
                return offset
            offset += int(self.capacity.get(b, 0))
        raise KeyError(block)

    def phys_slice(self, block: Block) -> slice:
        """某块当前**有效**数据在物理缓冲里的切片。"""
        start = self.phys_start(block)
        return slice(start, start + int(self.lengths[block]))

    def phys_total(self) -> int:
        """整个物理缓冲的长度（各块容量之和）。"""
        return sum(int(self.capacity.get(b, 0)) for b in PHYSICAL_ORDER)

    # ------------------------------------------------------------ 视图信息
    def start(self, block: Block, view: View) -> int:
        """某块在指定视图里的逻辑起点。"""
        offset = 0
        for item in VIEW_ORDER[view]:
            if item is block:
                return offset
            offset += self.lengths[item]
        raise KeyError(f"{block} 不在视图 {view} 里")

    def order(self, view: View) -> tuple[Block, Block, Block]:
        """该视图下 KV 应当拼接的顺序。"""
        return VIEW_ORDER[view]

    def delta(self, query_block: Block, key_block: Block, view: View) -> int:
        """查询额外需要旋转的角度（以位置数计）。

        同块时为 0；跨块时等于两块起点之差。
        """
        return self.start(query_block, view) - self.start(key_block, view)

    def delta_table(self, query_block: Block, view: View) -> dict[Block, int]:
        """一行角度表：query_block 在 view 里对三个块分别要旋多少。"""
        return {kb: self.delta(query_block, kb, view)
                for kb in VIEW_ORDER[view]}


class BlockCache(Cache):
    """三块 KV 的物理容器。

    与 transformers 的接口约定（5.x `Cache.update`）：
        update(key_states, value_states, layer_idx, cache_kwargs) -> (keys, values)

    我们在这里做的额外事情：
      1. 按 `self.target_block` 决定新 token 落到哪一块；
      2. 返回 **按当前视图顺序拼接** 的 K/V，让 attention 只需按块切分；
      3. 把 `sin/cos` 里的位置信息丢掉 —— 我们每层用同一套 delta，键的旋转
         已经由 `position_ids` 在 attention 之前完成。

    注意：这里假设"每步每个视图只追加 1 个 token"。批量追加（prefill）走
    `append_prefill`，由 `reference`/engine 在填 P 时调用。
    """

    def __init__(self, layout: BlockLayout, view: View = View.WRITER,
                 target_block: Block = Block.WRITER) -> None:
        # transformers 5.x 的 Cache.__init__ 要求"layers 与 layer_class_to_replicate
        # 恰好给一个"，传空列表即可；4.x 的签名不接受参数，故做一次回退。
        try:
            super().__init__(layers=[])
        except TypeError:  # pragma: no cover - 4.x 路径
            super().__init__()  # type: ignore[misc]
        self.layout = layout
        self.view = view
        self.target_block = target_block
        #: 本次 forward 正在写入、还没算作"已有上下文"的 token 数。
        #: layout 在 forward 前就已前移（attention 要按新长度切块），
        #: 但 cache_position 必须按"前移之前"的长度算，所以这里做减法。
        self.pending = 0
        #: layer_idx -> (k, v) 固定容量的物理缓冲（整层一块，零分配）
        self.buf: dict[int, tuple[torch.Tensor, torch.Tensor]] = {}
        #: 批处理模式：本次前向的每一行分别写入哪个块（None = 单行）
        self.target_blocks: list[Block] | None = None
        #: 批处理模式：每一行对应的 (视图, 自己的块)
        self.rows: list[tuple[View, Block]] | None = None
        #: 每块的写入位置索引张量（CUDA Graph 友好：位置是"数据"不是主机逻辑）
        self.widx: dict[Block, torch.Tensor] = {}

    # ------------------------------------------------------------ 写入
    def update(self, key_states, value_states, layer_idx, cache_kwargs=None):
        """就地写入预分配缓冲，返回视图顺序的拼接结果。

        性能要点（这是"开头很快、后来越来越慢"的修复）：
        旧实现每层每步都 `torch.cat([old_k, key_states])`，上下文长到 n 时
        单步拷贝 O(n)，n 步累计 **O(n²)**。现在改成
        **容量倍增 + 就地写入**，摊销 O(1)：只有容量不够时才搬一次数据，
        而容量翻倍使搬运次数是 O(log n)。
        """
        block = self.target_block

        if self.target_blocks is not None and key_states.shape[0] == len(self.target_blocks):
            # 批处理模式：每一行写进它自己的块（row0 -> T，row1 -> W）
            for row, blk in enumerate(self.target_blocks):
                self._write_one(layer_idx, blk,
                                key_states[row:row + 1], value_states[row:row + 1])
            return self.union_tensors(layer_idx)

        self._write_one(layer_idx, block, key_states, value_states)
        return self.union_tensors(layer_idx)

    def _write_one(self, layer_idx: int, block: Block,
                   key_states: torch.Tensor, value_states: torch.Tensor) -> None:
        """就地写入固定容量的物理缓冲（零分配，CUDA Graph 友好）。"""
        total = self.layout.phys_total()
        if total <= 0:
            raise RuntimeError("BlockLayout.capacity 未设置：请在 reset() 里先定好每块容量")

        buf = self.buf.get(layer_idx)
        if buf is None:
            shape = (*key_states.shape[:2], total, key_states.shape[3])
            self.buf[layer_idx] = (
                key_states.new_zeros(shape),
                value_states.new_zeros(shape),
            )
            buf = self.buf[layer_idx]
        buf_k, buf_v = buf

        n_new = key_states.shape[2]
        have = self.layout.lengths[block] - n_new
        if have < 0:
            have = 0
        start = self.layout.phys_start(block) + have
        if start + n_new > self.layout.phys_start(block) + self.layout.capacity[block]:
            raise RuntimeError(
                f"块 {block.name} 超出预分配容量 {self.layout.capacity[block]}"
                f"（需要 {have + n_new}）：请调大 reset 里的容量")
        # 用 index_copy_ 而不是切片赋值：
        # 切片偏移是"主机逻辑"，CUDA Graph 捕获时会被焊死；而 index_copy_ 的
        # 目标位置来自**张量内容**，可以在图外每步 .copy_() 更新，图才能复用。
        idx = self._write_idx(block, n_new, key_states.device)
        buf_k.index_copy_(2, idx, key_states)
        buf_v.index_copy_(2, idx, value_states)

    def _write_idx(self, block: Block, n_new: int, device) -> torch.Tensor:
        """取得（并按需更新）该块本次写入的位置索引张量。"""
        slot = self.widx.get(block)
        if slot is None or slot.numel() != n_new or slot.device != device:
            slot = torch.zeros(n_new, dtype=torch.long, device=device)
            self.widx[block] = slot
        start = self.layout.phys_start(block) + max(
            0, self.layout.lengths[block] - n_new)
        slot.copy_(torch.arange(start, start + n_new, dtype=torch.long, device=device))
        return slot

    # ------------------------------------------------------------ 读取
    def union_tensors(self, layer_idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        """返回整层固定缓冲（零拷贝）。

        缓冲布局是 [P 容量][T 容量][W 容量]，各块在固定偏移上；
        消费方（attention）用 `layout.phys_slice(block)` 取自己那一段。
        所以这里**不拼接、不分配** —— CUDA Graph 才能捕获。
        """
        buf = self.buf.get(layer_idx)
        if buf is None:
            raise RuntimeError("BlockCache 为空：请先 append 至少一个 token")
        return buf

    # ------------------------------------------------------------ 元信息
    def get_seq_length(self, layer_idx: int = 0) -> int:
        """**当前视图**的可见长度（不含本次在途 token）。

        transformers 拿这个值推 cache_position，所以必须是"视图内逻辑长度"，
        不是物理总长度 —— 每个视图都有一整个 Prompt Block / linker 看不见。
        """
        if self.rows:
            # 批处理：各行的视图长度不同，取最大值（decode 时不需要掩码）
            return max(0, max(self.layout.view_total(v) for v, _ in self.rows)
                       - int(self.pending))
        return max(0, self.layout.view_total(self.view) - int(self.pending))

    def get_max_length(self) -> None:
        """动态缓存没有上限；返回 None 与 transformers 约定一致。"""
        return None

    # ------------------------------------------------------------ 收缩
    def truncate(self, block: Block, length: int) -> None:
        """把某块的**可见长度**截回 length（虚拟截断，不搬数据）。

        用途：插探针判定后"隐藏"探针那几个 token 的 KV。
        现在数据放在固定容量缓冲里，可见性完全由 `layout.lengths[block]` 决定，
        所以这里**不需要**复制/裁剪张量：
          * `view_tensors` 只切到 layout 的长度 → 截掉的部分自然看不见；
          * 之后的新 token 写到 `have = layout.lengths[block]` 处，正好覆盖旧数据。
        旧实现在这里做 `.contiguous()` 会把容量缓冲缩掉，与倍增策略冲突。
        """
        _ = (block, length)   # 可见长度由调用方通过 layout.set_len 更新


def block_slices(layout: BlockLayout, view: View) -> list[tuple[Block, slice]]:
    """给出视图顺序下每块在拼接张量里的切片，供 attention 切分。

    返回 [(block, slice), ...]，例如 Writer 视图：
        [(P, 0:p), (T, p:p+t), (W, p+t:p+t+w)]
    """
    result: list[tuple[Block, slice]] = []
    offset = 0
    for block in layout.order(view):
        size = layout.lengths[block]
        result.append((block, slice(offset, offset + size)))
        offset += size
    return result


#: 物理存放顺序（与视图无关）：union_tensors 就是这个顺序
PHYSICAL_ORDER: tuple[Block, ...] = (Block.PROMPT, Block.THINKER, Block.WRITER)


def physical_slices(layout: BlockLayout) -> dict[Block, slice]:
    """每块在物理缓冲里的有效切片（固定容量偏移 + 当前长度）。"""
    return {block: layout.phys_slice(block) for block in PHYSICAL_ORDER}
