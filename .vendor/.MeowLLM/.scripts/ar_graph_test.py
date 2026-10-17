# -*- coding: utf-8 -*-
"""验证：CUDA Graph 能否吃掉 Windows 下每 kernel 的驱动开销。

做法：同一个固定形状的模型前向，
  A. eager 反复调
  B. 用 torch.cuda.CUDAGraph 抓一次，之后只 replay
若 B 远快于 A，说明瓶颈确实是"每次提交"的固定开销，图形化就是正解。

（不要求 cache 静态，用 use_cache=False 的整段前向；只为验证机制。）
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

ids = torch.tensor([tok("hello " * 60, add_special_tokens=False)["input_ids"][:64]],
                   device=dev, dtype=torch.long)
pos = torch.arange(ids.shape[1], device=dev).unsqueeze(0)


def timed(fn, reps=20):
    for _ in range(5):
        fn()
    torch.cuda.synchronize()
    s = []
    for _ in range(reps):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        fn()
        torch.cuda.synchronize()
        s.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(s)


def eager():
    with torch.no_grad():
        model(input_ids=ids, position_ids=pos, use_cache=False)


ms_eager = timed(eager)
print(f"A eager        : {ms_eager:7.2f} ms   (64 token 整段前向)")

# ---- CUDA Graph 捕获 ----
try:
    side = torch.cuda.Stream()
    side.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(side):
        for _ in range(3):
            eager()
    torch.cuda.current_stream().wait_stream(side)
    torch.cuda.synchronize()
    torch.cuda.empty_cache()

    g = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g):
        out = model(input_ids=ids, position_ids=pos, use_cache=False)
    torch.cuda.synchronize()

    def replay():
        g.replay()

    ms_graph = timed(replay)
    print(f"B cuda-graph    : {ms_graph:7.2f} ms   -> {ms_eager / ms_graph:.2f}x")
    print("")
    if ms_graph < ms_eager * 0.5:
        print("判定：**图形化有效**，瓶颈是提交开销。值得把缓存改成静态缓冲后上图。")
    else:
        print("判定：图形化收益有限，说明时间花在 kernel 执行本身。")
except Exception as exc:  # noqa: BLE001
    print(f"B cuda-graph    : 捕获失败 {type(exc).__name__}: {str(exc)[:160]}")
