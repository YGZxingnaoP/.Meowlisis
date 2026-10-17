# -*- coding: utf-8 -*-
"""在 0.6B 上测 torch.compile 对单 token 解码的收益（不动引擎）。

三种配置对比：
  baseline         : 原生 eager
  compile-default  : torch.compile(mode="default")   只做内核融合
  compile-graph    : torch.compile(mode="reduce-overhead")  CUDA Graph

注意：CUDA Graph 要求显存地址固定。我们的块缓存已经预分配（地址稳定），
但 view_tensors 里还有 torch.cat（每步新张量）——所以 reduce-overhead 可能
报错或回退。这里如实测出来。
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


def build():
    m = AutoModelForCausalLM.from_pretrained(
        MODEL, dtype=torch.bfloat16, device_map="cuda").eval()
    ids = torch.tensor([[tok("hello " * 10, add_special_tokens=False)["input_ids"][0]]],
                       device=dev, dtype=torch.long)
    pos = torch.arange(ids.shape[1], device=dev).unsqueeze(0)
    with torch.no_grad():
        out = m(input_ids=ids, position_ids=pos, use_cache=True)
    return m, out.past_key_values, torch.tensor([[1000]], device=dev, dtype=torch.long), \
        torch.tensor([[ids.shape[1]]], device=dev, dtype=torch.long)


def measure(m, past, one, p1, reps=20) -> tuple[float, float]:
    def step():
        with torch.no_grad():
            m(input_ids=one, position_ids=p1, past_key_values=past, use_cache=True)

    for _ in range(5):
        step()
    torch.cuda.synchronize()
    samples = []
    for _ in range(reps):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        step()
        torch.cuda.synchronize()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples), min(samples)


print("=" * 60)
m, past, one, p1 = build()
med, mn = measure(m, past, one, p1)
print(f"baseline        median={med:6.2f} ms   min={mn:6.2f} ms")
base = med
del m, past
torch.cuda.empty_cache()

for mode in ("default", "reduce-overhead"):
    print("=" * 60)
    try:
        m, past, one, p1 = build()
        t0 = time.perf_counter()
        cm = torch.compile(m, mode=mode, dynamic=False)
        med, mn = measure(cm, past, one, p1, reps=15)
        print(f"compile-{mode:<12} median={med:6.2f} ms   min={mn:6.2f} ms"
              f"   ({base / med:.2f}x)   编译 {time.perf_counter() - t0:.0f}s")
    except Exception as exc:  # noqa: BLE001
        print(f"compile-{mode:<12} 失败: {type(exc).__name__}: {str(exc)[:140]}")
    try:
        del m
    except Exception:  # noqa: BLE001
        pass
    torch.cuda.empty_cache()

print("=" * 60)
print("若某个 mode 明显低于 baseline，就把它接进引擎；否则说明必须靠量化。")
