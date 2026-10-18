# -*- coding: utf-8 -*-
"""定位"每步 0.16s"到底花在哪。

对同一个模型、同一段上下文，分别计时：
  A. 我们的块注意力（dualstream）单 token 前向
  B. 原生 sdpa + DynamicCache 单 token 前向（基线）
  C. 只做采样 + 解码（不含前向）
  D. 我们的 attention 内部：逐块 matmul 的总耗时占比

B/A 的比值说明"是不是我们的 attention 拖慢的"。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import torch

MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

from meowllm.engine.dualstream.blocks import Block, BlockLayout, View  # noqa: E402
from meowllm.engine.dualstream.attention import attach  # noqa: E402
from meowllm.engine.dualstream.loop import DualStreamLoop  # noqa: E402

MODEL = str(MODULE_ROOT / "models" / "Qwen3-0.6B")
N = 40          # 预热步数
REPS = 20       # 计步数


def timeit(fn, reps=REPS):
    for _ in range(5):
        fn()
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(reps):
        fn()
    torch.cuda.synchronize()
    return (time.perf_counter() - t0) / reps * 1000.0


def main() -> int:
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, dtype=torch.bfloat16, device_map="cuda").eval()
    # attach 由 DualStreamLoop.__init__ 完成（需要 ctx），这里不再手动调用

    msgs = [{"role": "user", "content": "What is 5 - 25 + 125?"}]
    loop = DualStreamLoop(model, tok, probe_every=10 ** 9,
                          device="cuda")
    loop.reset(msgs)

    # 推到 N 步，让上下文变长
    for _ in range(N):
        loop.step()
    torch.cuda.synchronize()
    lens = dict(loop.layout.lengths)
    print(f"上下文：P={lens[Block.PROMPT]} T={lens[Block.THINKER]} W={lens[Block.WRITER]}"
          f"  视图长度 writer={loop.layout.view_total(View.WRITER)}")

    # ---------- A: 我们的单 token 前向 ----------
    token = 1234
    ms_a = timeit(lambda: loop._forward([token], Block.THINKER, View.THINKER))
    print(f"A 我方块注意力 单 token 前向 : {ms_a:7.2f} ms")

    # ---------- B: 原生 sdpa + DynamicCache ----------
    old = getattr(model.config, "_attn_implementation", None)
    model.config._attn_implementation = "sdpa"  # noqa: SLF001
    from transformers import DynamicCache
    cache = DynamicCache()
    ids = torch.tensor([[tok("hello world " * 20, add_special_tokens=False)["input_ids"][0]]],
                       device="cuda", dtype=torch.long)
    pos = torch.arange(ids.shape[1], device="cuda").unsqueeze(0)
    with torch.no_grad():
        model(input_ids=ids, position_ids=pos, past_key_values=cache, use_cache=True)
    one = torch.tensor([[token]], device="cuda", dtype=torch.long)
    step_pos = torch.tensor([[ids.shape[1]]], device="cuda", dtype=torch.long)

    def sdpa_step():
        with torch.no_grad():
            model(input_ids=one, position_ids=step_pos,
                  past_key_values=cache, use_cache=True)

    ms_b = timeit(sdpa_step)
    model.config._attn_implementation = old  # noqa: SLF001
    print(f"B 原生 sdpa 单 token 前向     : {ms_b:7.2f} ms")
    print(f"   → A/B 倍数 = {ms_a / max(ms_b, 1e-9):.1f}x")

    # ---------- C: 采样 + 解码开销 ----------
    logits = loop.thinker_logits
    ms_c = timeit(lambda: loop._decode(loop._sample(logits)), reps=200)
    print(f"C 采样 + 解码（无前向）        : {ms_c:7.3f} ms")

    # ---------- D: 整个 step ----------
    ms_d = timeit(lambda: loop.step(), reps=10)
    print(f"D 整个 step（2 次前向）        : {ms_d:7.2f} ms")

    print("")
    print(f"结论线索：A 若接近 B×2 以上，说明瓶颈在我们自己的 attention；")
    print(f"         A≈B 但 D 远大于 2×A，说明瓶颈在 step 的其它部分（探针/采样/记账）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
