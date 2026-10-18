# -*- coding: utf-8 -*-
"""二分定位：从"只有 P 块"开始，逐步加入 T/W，看对拍在第几步开始崩。

用途：当 ar_p1_smoke.py 的 T4 失败时，用本脚本判断问题出在
      ① 单块注意力实现本身，还是 ② 多块 delta 旋转。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import torch

MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

from meowllm.engine.dualstream.blocks import Block, View  # noqa: E402
from meowllm.engine.dualstream.compat import encode_chat  # noqa: E402
from meowllm.engine.dualstream.loop import DualStreamLoop  # noqa: E402
from meowllm.engine.dualstream.reference import next_token_logits  # noqa: E402


def cmp(tag: str, ours: torch.Tensor, ref: torch.Tensor) -> None:
    cos = torch.nn.functional.cosine_similarity(
        ours.unsqueeze(0), ref.unsqueeze(0)).item()
    delta = (ours - ref).abs().max().item()
    same = int(ours.argmax()) == int(ref.argmax())
    flag = "OK  " if cos > 0.999 else "BAD "
    print(f"  {flag}{tag:<28} cos={cos:.6f}  max|Δ|={delta:.3e}  top1同={same}")


def main() -> int:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    mdir = MODULE_ROOT / "models" / "Qwen3-0.6B"
    tok = AutoTokenizer.from_pretrained(mdir)
    model = AutoModelForCausalLM.from_pretrained(
        mdir, dtype=torch.bfloat16, device_map=device).eval()

    messages = [{"role": "user", "content": "3 的平方加上 4 的平方等于多少？"}]
    loop = DualStreamLoop(model=model, tokenizer=tok,
                          thinker_max=8, writer_max=8, probe_every=9999,
                          device=device, temperature=0.0, seed=1)

    # ---- 用手工步骤还原 reset，以便在每一步之后都做对拍 ----
    system = loop.marks["thinker_system"] + "\n\n" + loop.marks["writer_system"]
    prompt_ids = encode_chat(tok, [{"role": "system", "content": system}] + messages)
    loop.prompt_ids = prompt_ids
    logits_p = loop._forward(prompt_ids, Block.PROMPT, View.WRITER)  # noqa: SLF001
    ref_p = next_token_logits(model, prompt_ids, [], [], View.WRITER, device)
    print("\n[1] 只有 P（单块，delta 全为 0）")
    cmp("P only / writer view", logits_p, ref_p)

    # 加 T 标记
    t_ids = loop._encode("<think>")
    loop.thinker_ids = list(t_ids)
    logits_t = loop._forward(t_ids, Block.THINKER, View.THINKER)  # noqa: SLF001
    ref_t = next_token_logits(model, prompt_ids, loop.thinker_ids, [],
                              View.THINKER, device)
    print("\n[2] 加上 T 标记（thinker 视图：P -> T）")
    cmp("P+T / thinker view", logits_t, ref_t)

    # 加 W 标记
    w_ids = loop._encode("我说：")
    loop.writer_ids = list(w_ids)
    logits_w = loop._forward(w_ids, Block.WRITER, View.WRITER)  # noqa: SLF001
    ref_w = next_token_logits(model, prompt_ids, loop.thinker_ids, loop.writer_ids,
                              View.WRITER, device)
    print("\n[3] 加上 W 标记（writer 视图：P -> T -> W，三块齐全）")
    cmp("P+T+W / writer view", logits_w, ref_w)

    # 再加一个 W token
    logits_w2 = loop._forward([1000], Block.WRITER, View.WRITER)  # noqa: SLF001
    loop.writer_ids.append(1000)
    ref_w2 = next_token_logits(model, prompt_ids, loop.thinker_ids, loop.writer_ids,
                               View.WRITER, device)
    print("\n[4] 再追加一个 W token")
    cmp("P+T+W+1 / writer view", logits_w2, ref_w2)

    print("\n结论：哪一步开始 BAD，问题就在那一层。")
    print("  第 1 步 BAD  -> 自定义 attention 本身有问题（缩放/头布局/掩码）")
    print("  第 2 步 BAD  -> T 块的位置或视图顺序有问题")
    print("  第 3 步 BAD  -> 三块 delta 旋转有问题")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
