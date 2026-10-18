# -*- coding: utf-8 -*-
"""验证 CUDA Graph 是否真的生效、以及是否引入数值偏差。

做法：贪心采样（argmax，消除随机性），跑两条路径各 6 步：
  A. 允许用图（_graph_ok=True）
  B. 强制不用图（_graph_ok=False）
比较：token 序列是否完全一致 / 步耗时 / graph_disabled 是否被置位。
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
sys.path.insert(0, ROOT)

from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

from meowllm.engine.dualstream.loop import DualStreamLoop  # noqa: E402

tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(
    MODEL, dtype=torch.bfloat16, device_map="cuda").eval()
MSGS = [{"role": "user", "content": "What is 5 - 25 + 125?"}]
STEPS = 6


def run(use_graph: bool):
    loop = DualStreamLoop(model, tok,
                          probe_every=10 ** 9, device="cuda")
    loop._graph_ok = use_graph                 # 关键开关
    loop._sample = lambda logits: int(logits.argmax().item())   # 贪心，确定性
    loop.reset(MSGS)
    times = []
    for _ in range(STEPS):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        loop.step()
        torch.cuda.synchronize()
        times.append((time.perf_counter() - t0) * 1000.0)
    return (list(loop.thinker_ids), list(loop.writer_ids),
            statistics.median(times), getattr(loop.stats, "graph_disabled", None))


t_a, w_a, ms_a, disabled_a = run(True)
t_b, w_b, ms_b, disabled_b = run(False)

print(f"A 用图 : {ms_a:7.2f} ms/step   graph_disabled={disabled_a}")
print(f"B 不用 : {ms_b:7.2f} ms/step")
print(f"加速   : {ms_b / ms_a:.2f}x")
print(f"thinker 序列一致: {t_a == t_b}")
print(f"writer  序列一致: {w_a == w_b}")
if t_a != t_b:
    print(f"  A thinker = {t_a}")
    print(f"  B thinker = {t_b}")
if w_a != w_b:
    print(f"  A writer  = {w_a}")
    print(f"  B writer  = {w_b}")
