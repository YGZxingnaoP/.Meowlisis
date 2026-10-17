# -*- coding: utf-8 -*-
"""决定性判定：单步 31 ms 里，GPU 内核真正占多少时间。

  kernel 总时间 ≈ 31 ms  -> GPU 在这些形状上就是慢（内核选择/driver 问题）
  kernel 总时间 << 31 ms  -> 时间花在等待/依赖停顿上（与缓存逻辑无关）
"""

import os
import sys

import torch
from torch.profiler import ProfilerActivity, profile

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


def step():
    with torch.no_grad():
        model(input_ids=one, position_ids=p1, past_key_values=past, use_cache=True)


for _ in range(5):
    step()
torch.cuda.synchronize()

REPS = 10
ev0, ev1 = torch.cuda.Event(True), torch.cuda.Event(True)
ev0.record()
for _ in range(REPS):
    step()
ev1.record()
torch.cuda.synchronize()
wall = ev0.elapsed_time(ev1) / REPS
print(f"单步墙钟（GPU 时间轴）= {wall:.2f} ms")

with profile(activities=[ProfilerActivity.CUDA]) as prof:
    for _ in range(REPS):
        step()
    torch.cuda.synchronize()

total_kernel = 0.0
total_count = 0
rows = []
for e in prof.key_averages():
    if e.self_device_time_total <= 0:
        continue
    total_kernel += e.self_device_time_total
    total_count += e.count
    rows.append((e.self_device_time_total / 1000.0 / REPS, e.count / REPS, e.key))
total_kernel /= REPS * 1000.0
total_count //= REPS

print(f"单步 kernel 数        = {total_count}")
print(f"单步 kernel 总时间     = {total_kernel:.2f} ms")
print(f"空闲/停顿占比          = {(1 - total_kernel / wall) * 100:.1f}%")
print("\n耗时最高的 8 个 kernel（ms/步）:")
for ms, cnt, key in sorted(rows, reverse=True)[:8]:
    print(f"  {ms:8.3f}  x{cnt:>4.0f}  {key[:70]}")

print("")
if total_kernel > wall * 0.7:
    print("判定：**GPU 真的在算**，这些形状上内核本身慢（driver/内核选择问题）")
    print("      -> 缓存逻辑再怎么改也没用；应换 torch 版本/开 torch.compile/换卡")
else:
    print("判定：**停顿为主**，GPU 大部分时间空转")
    print("      -> 时间花在依赖链等待或主机侧，与 KV 缓存无关")
