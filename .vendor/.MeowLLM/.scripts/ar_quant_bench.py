# -*- coding: utf-8 -*-
"""0.6B 4bit/8bit 量化后单 token 解码速度实测。

权重体积决定 decode 速度：bf16 1.2GB -> 8bit 0.6GB -> 4bit 0.3GB。
预期：8bit 约 1.8x，4bit 约 3x。
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
ids = torch.tensor([[tok("hello " * 10, add_special_tokens=False)["input_ids"][0]]],
                   device=dev, dtype=torch.long)
pos = torch.arange(ids.shape[1], device=dev).unsqueeze(0)


def bench(model, reps=15):
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
    samples = []
    for _ in range(reps):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        step()
        torch.cuda.synchronize()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples)


def load(kind):
    from transformers import BitsAndBytesConfig

    if kind == "bf16":
        return AutoModelForCausalLM.from_pretrained(
            MODEL, dtype=torch.bfloat16, device_map="cuda").eval()
    if kind == "int8":
        qc = BitsAndBytesConfig(load_in_8bit=True)
    else:
        qc = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
    return AutoModelForCausalLM.from_pretrained(
        MODEL, quantization_config=qc, device_map="cuda").eval()


base = None
for kind in ("bf16", "int8", "int4"):
    print("=" * 56)
    try:
        m = load(kind)
        mem = torch.cuda.memory_allocated() / 1e9
        ms = bench(m)
        if base is None:
            base = ms
        print(f"{kind:>5} : {ms:6.2f} ms/token   {base / ms:4.2f}x   "
              f"显存 {mem:.2f} GB   {1000 / ms:5.1f} tok/s")
    except Exception as exc:  # noqa: BLE001
        print(f"{kind:>5} : 失败 {type(exc).__name__}: {str(exc)[:120]}")
    try:
        del m
    except Exception:  # noqa: BLE001
        pass
    torch.cuda.empty_cache()

print("=" * 56)
