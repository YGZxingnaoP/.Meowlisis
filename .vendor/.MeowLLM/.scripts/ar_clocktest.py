# -*- coding: utf-8 -*-
"""判定：单 token 前向的 31ms 是「真的慢」还是「时钟没升上来/间歇停顿」。

只做一件事：连续跑 50 次同一前向，统计 min / median / max。
  min ≈ 5-10 ms, median 30+  -> 停顿/降频为主（第一次慢，后面有些快）
  全部 ≈ 30 ms                -> 真的慢（内核在这些形状上就这速度）
"""
import os
import statistics
import sys
import time

import torch

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "models", "Qwen3-0.6B")

from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

dev = torch.device("cuda:0")
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(
    MODEL, dtype=torch.bfloat16, device_map="cuda").eval()

ids = torch.tensor([[tok("hello " * 10, add_special_tokens=False)["input_ids"][0]]],
                   device=dev, dtype=torch.long)
pos = torch.arange(ids.shape[1], device=dev).unsqueeze(0)
with torch.no_grad():
    out = model(input_ids=ids, position_ids=pos, use_cache=True)
past = out.past_key_values
one = torch.tensor([[1000]], device=dev, dtype=torch.long)
p1 = torch.tensor([[ids.shape[1]]], device=dev, dtype=torch.long)


def forward_once() -> float:
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    with torch.no_grad():
        model(input_ids=one, position_ids=p1, past_key_values=past, use_cache=True)
    torch.cuda.synchronize()
    return (time.perf_counter() - t0) * 1000.0


def load_gpu(seconds: float = 2.0) -> None:
    """持续满载，把时钟顶上去。"""
    a = torch.randn(4096, 4096, device=dev, dtype=torch.bfloat16)
    b = torch.randn(4096, 4096, device=dev, dtype=torch.bfloat16)
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        for _ in range(5):
            _ = a @ b
        torch.cuda.synchronize()


for _ in range(10):
    forward_once()

samples1 = [forward_once() for _ in range(50)]
print("=== 无额外负载（连续 50 次）===")
print(f"  min={min(samples1):.2f}  median={statistics.median(samples1):.2f}  max={max(samples1):.2f} ms")

print("=== 先把 GPU 顶满 2 秒，再测 ===")
load_gpu(2.0)
samples2 = [forward_once() for _ in range(50)]
print(f"  min={min(samples2):.2f}  median={statistics.median(samples2):.2f}  max={max(samples2):.2f} ms")

print("")
m1, m2 = statistics.median(samples1), statistics.median(samples2)
if m2 < m1 * 0.7:
    print(f"判定：预热后快 {m1/m2:.1f}x  -> **是时钟/功耗状态问题**")
    print("      修法：nvidia-smi -lgc 1500,3090（需管理员）锁频，或后台保活占空")
elif min(samples1 + samples2) < 15 and m1 > 25:
    print("判定：min 很低但 median 高 -> **间歇停顿**（依赖链等待/驱动）")
else:
    print("判定：**稳定地慢**，内核在这些形状上就这速度 -> 换 torch/开 torch.compile/换卡")
