# -*- coding: utf-8 -*-
"""确认：模型到底在不在 GPU 上？GPU 本身有多快？

三个独立证据：
  1. 模型参数所在的 device / dtype
  2. GPU 纯度测试：显存带宽 + matmul 算力（与模型无关，验证卡本身）
  3. 模型单 token 前向的 CUDA 事件计时（事件计的是 GPU 时间，不受主机噪声影响）
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
    print(f"torch {torch.__version__}  cuda {torch.version.cuda}")
    print(f"available={torch.cuda.is_available()}  count={torch.cuda.device_count()}")
    if not torch.cuda.is_available():
        print("CUDA 不可用：模型必然在 CPU 上")
        return 1
    for i in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(i)
        print(f"  device[{i}] {p.name}  {p.total_memory/1e9:.1f} GB  cap sm_{p.major}{p.minor}")

    dev = torch.device("cuda:0")
    print(f"\n当前设备 = {torch.cuda.current_device()}")

    # ---------- 2. GPU 纯度测试 ----------
    a = torch.randn(8192, 8192, device=dev, dtype=torch.bfloat16)
    b = torch.randn(8192, 8192, device=dev, dtype=torch.bfloat16)
    for _ in range(3):
        _ = a @ b
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(10):
        _ = a @ b
    torch.cuda.synchronize()
    dt = (time.perf_counter() - t0) / 10
    tflops = 2 * 8192 ** 3 / dt / 1e12
    print(f"\n[GPU 算力] 8192^3 bf16 matmul: {dt*1000:.1f} ms  =  {tflops:.1f} TFLOPS")
    print("   参考：RTX 5060 Laptop bf16 约 30-60 TFLOPS；若只有个位数说明降频严重")

    # 显存带宽（整块拷贝）
    src = torch.empty(512 * 1024 * 1024 // 2, device=dev, dtype=torch.bfloat16)  # 512MB
    dst = torch.empty_like(src)
    for _ in range(3):
        dst.copy_(src)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(20):
        dst.copy_(src)
    torch.cuda.synchronize()
    dt = (time.perf_counter() - t0) / 20
    bw = 2 * src.numel() * 2 / dt / 1e9      # 读+写
    print(f"[显存带宽] 512MB 拷贝: {dt*1000:.2f} ms  =  {bw:.0f} GB/s")
    print("   参考：RTX 5060 Laptop 约 300-400 GB/s")

    # ---------- 1 + 3. 模型真实位置与前向计时 ----------
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, dtype=torch.bfloat16, device_map="cuda").eval()

    p0 = next(model.parameters())
    print(f"\n[模型位置] 参数 device={p0.device}  dtype={p0.dtype}")
    on_cuda = sum(1 for t in model.parameters() if t.device.type == "cuda")
    total = sum(1 for _ in model.parameters())
    print(f"[模型位置] 在 CUDA 上的参数张量: {on_cuda}/{total}")
    try:
        print(f"[显存占用] allocated={torch.cuda.memory_allocated()/1e9:.2f} GB")
    except Exception:  # noqa: BLE001
        pass

    ids = torch.tensor([[tok("hello world " * 20, add_special_tokens=False)["input_ids"][0]]],
                       device=dev, dtype=torch.long)
    pos = torch.arange(ids.shape[1], device=dev).unsqueeze(0)
    with torch.no_grad():
        out = model(input_ids=ids, position_ids=pos, use_cache=True)
    past = out.past_key_values
    last = out.logits[0, -1]
    print(f"[logits] device={last.device}  shape={tuple(last.shape)}")

    one = torch.tensor([[1234]], device=dev, dtype=torch.long)
    p1 = torch.tensor([[ids.shape[1]]], device=dev, dtype=torch.long)

    def step():
        with torch.no_grad():
            return model(input_ids=one, position_ids=p1, past_key_values=past, use_cache=True)

    for _ in range(5):
        step()
    torch.cuda.synchronize()

    # CUDA 事件计时：只测 GPU 时间
    ev0, ev1 = torch.cuda.Event(True), torch.cuda.Event(True)
    ev0.record()
    for _ in range(20):
        step()
    ev1.record()
    torch.cuda.synchronize()
    gpu_ms = ev0.elapsed_time(ev1) / 20
    print(f"[前向] 单 token（CUDA 事件计时）= {gpu_ms:.2f} ms")
    print(f"   0.6B bf16 正常应在 3-8 ms；>30 ms 说明没吃到 GPU 或严重降频")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
