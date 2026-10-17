# -*- coding: utf-8 -*-
"""判定：单 token 前向到底是 GPU 算得慢，还是 CPU 发射 kernel 太慢。

判据
----
* 若 **launch-bound**（CPU 发射瓶颈）：
      batch=1 和 batch=8 的墙钟时间几乎一样 —— 因为 kernel 数量不变，
      只是每个 kernel 多一点数据。GPU 利用率会很低（任务管理器显示 0%）。
* 若 **compute/bandwidth-bound**：
      时间大致随 batch 线性增长。

这一测直接决定优化方向：
    launch-bound  -> 合并 batch（两条流合成一次前向）能白拿 ~2x
    bandwidth-bound -> 只能换更快的卡或更小的模型
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

MODEL = str(MODULE_ROOT / "models" / "Qwen3-0.6B")


def main() -> int:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, dtype=torch.bfloat16, device_map="cuda").eval()
    dev = torch.device("cuda:0")
    print(f"model on {next(model.parameters()).device}\n")

    def bench(batch: int, use_cache_steps: int = 0) -> float:
        """对新生成 1 个 token 计时（带 cache，模拟解码）。"""
        ids = torch.full((batch, 1), 1000, device=dev, dtype=torch.long)
        pos = torch.zeros((batch, 1), device=dev, dtype=torch.long)
        with torch.no_grad():
            out = model(input_ids=ids, position_ids=pos, use_cache=True)
        past = out.past_key_values
        nxt = torch.full((batch, 1), 1000, device=dev, dtype=torch.long)
        npos = torch.ones((batch, 1), device=dev, dtype=torch.long)

        def step():
            with torch.no_grad():
                model(input_ids=nxt, position_ids=npos,
                      past_key_values=past, use_cache=True)

        for _ in range(5):
            step()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(20):
            step()
        torch.cuda.synchronize()
        return (time.perf_counter() - t0) / 20 * 1000.0

    print("batch   单步墙钟(ms)   相对 batch=1")
    base = None
    for b in (1, 2, 4, 8):
        ms = bench(b)
        if base is None:
            base = ms
        print(f"  {b:>2}      {ms:8.2f}        {ms / base:5.2f}x")

    print()
    print("判读：")
    print("  若 8 行的耗时 ≈ 1 行（<1.8x）-> **launch-bound**，合并 batch 能白拿 ~2x")
    print("  若 8 行耗时 ≈ 8 行线性增长     -> 带宽/算力受限，只能换卡或换小模型")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
