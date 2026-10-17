# -*- coding: utf-8 -*-
"""查 kernel 发射开销与致命环境变量（短版，不加载模型）。"""
import os
import sys
import time

import torch

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

WATCH = ["CUDA_LAUNCH_BLOCKING", "PYTORCH_NO_CUDA_MEMORY_CACHING",
         "PYTORCH_CUDA_ALLOC_CONF", "TORCH_CUDA_ALLOC_CONF",
         "CUDA_VISIBLE_DEVICES", "CUBLAS_WORKSPACE_CONFIG",
         "OMP_NUM_THREADS", "TORCHDYNAMO_DISABLE", "TORCH_COMPILE_DISABLE"]

print("=== 环境变量 ===")
any_set = False
for k in WATCH:
    v = os.environ.get(k)
    if v is None:
        continue
    any_set = True
    bad = ""
    if k == "CUDA_LAUNCH_BLOCKING" and v.strip() in ("1", "true", "TRUE"):
        bad = "   <<< 致命：每次发射都同步"
    if k == "PYTORCH_NO_CUDA_MEMORY_CACHING" and v.strip() in ("1", "true", "TRUE"):
        bad = "   <<< 致命：每次分配都 cudaMalloc"
    print(f"  {k} = {v}{bad}")
if not any_set:
    print("  （都未设置）")

if not torch.cuda.is_available():
    print("CUDA 不可用")
    raise SystemExit(1)

dev = torch.device("cuda:0")
print(f"\nGPU = {torch.cuda.get_device_name(0)}")
print(f"allocator = {torch.cuda.get_allocator_backend()}")

x = torch.zeros(1, device=dev)
for _ in range(50):
    x.add_(1)
torch.cuda.synchronize()
n = 2000
t0 = time.perf_counter()
for _ in range(n):
    x.add_(1)
torch.cuda.synchronize()
per = (time.perf_counter() - t0) / n * 1e6
print(f"\n[kernel 发射] {per:.1f} us/次")
if per < 15:
    print("   -> 正常（5-15us）")
else:
    print(f"   -> 偏高：每步约 420 个 kernel x {per:.0f}us = {420*per/1000:.0f} ms")
    print("      足以解释 31ms/前向")

torch.cuda.empty_cache()
torch.cuda.synchronize()
t0 = time.perf_counter()
for _ in range(100):
    _ = torch.empty(1024, 1024, device=dev, dtype=torch.bfloat16)
torch.cuda.synchronize()
alloc = (time.perf_counter() - t0) / 100 * 1e6
print(f"[显存分配] {alloc:.1f} us/次")
if alloc > 1000:
    print("   -> 极慢：分配器没复用")
