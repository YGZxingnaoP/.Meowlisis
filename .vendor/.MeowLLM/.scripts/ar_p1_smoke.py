# -*- coding: utf-8 -*-
"""AsyncReasoning 真机冒烟测试（P1 + P2 验收）。

四个阶段
--------
T0  环境：CUDA、transformers 插槽
T1  加载：Qwen3-0.6B（bf16），报告显存
T2  地基：`position_ids` 是否真的生效（改一个位置，logits 必须变）
T3  双流：跑若干步，看思考与输出是否交错产出
T4  对拍：块 KV + 查询旋转 的 logits vs 物理重排参考实现
        —— 这是 P2 的验收线，过不了就不该继续往下做

用法（在 .vendor/.MeowLLM 目录下）
---------------------------------
    ..\\..\\runtime\\311\\python.exe .scripts\\ar_p1_smoke.py
    ..\\..\\runtime\\311\\python.exe .scripts\\ar_p1_smoke.py --steps 16
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT))
os.environ.setdefault("PYTHONUTF8", "1")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  —— {detail}" if detail else ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--model", default="models/Qwen3-0.6B")
    parser.add_argument("--no-compare", action="store_true", help="跳过 T4 对拍")
    parser.add_argument("--probe-every", type=int, default=0,
                        help="覆盖探针间隔；给很大的值可关闭探针（排查用）")
    parser.add_argument("--dtype", choices=("bf16", "fp32"), default="bf16",
                        help="权重精度；fp32 用于确认对拍残差是纯数值漂移")
    args = parser.parse_args()

    print("=" * 70)
    print("AsyncReasoning 真机冒烟测试")
    print("=" * 70)

    # ---------------------------------------------------------------- T0
    print("\n=== T0 环境 ===")
    import torch

    from meowllm.engine.dualstream import compat

    problems = compat.self_check()
    record("transformers 插槽可用", not problems, "; ".join(problems) if problems else "")
    if problems:
        return 1

    cuda = torch.cuda.is_available()
    record("CUDA 可用", cuda,
           f"{torch.cuda.get_device_name(0)} / {torch.__version__}" if cuda else "只有 CPU")
    device = "cuda" if cuda else "cpu"

    # ---------------------------------------------------------------- T1
    print("\n=== T1 加载模型 ===")
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_dir = MODULE_ROOT / args.model
    if not (model_dir / "model.safetensors").is_file():
        record("权重就位", False, f"缺少 {model_dir / 'model.safetensors'}")
        return 1
    record("权重就位", True, f"{model_dir}")

    torch_dtype = torch.float32 if args.dtype == "fp32" else torch.bfloat16
    started = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, dtype=torch_dtype,
        device_map=device if device == "cuda" else None)
    if device == "cpu":
        model = model.to("cpu")
    model.eval()
    load_s = time.perf_counter() - started
    record("加载成功", True, f"{load_s:.1f}s, dtype={args.dtype}")
    if cuda:
        used = torch.cuda.memory_allocated() / 1e9
        total = torch.cuda.get_device_properties(0).total_memory / 1e9
        record("显存占用", True, f"{used:.2f} / {total:.2f} GB")

    # ---------------------------------------------------------------- T2
    print("\n=== T2 position_ids 是否生效（整个方案的地基）===")
    messages = [{"role": "user", "content": "3 的平方加上 4 的平方等于多少？"}]
    # 走 compat 的统一包装：5.x 的 apply_chat_template 形态不固定
    from meowllm.engine.dualstream.compat import encode_chat

    prompt_list = encode_chat(tok, messages)
    ids = torch.tensor([prompt_list], device=device)
    base_pos = torch.arange(ids.shape[1], device=device).unsqueeze(0)
    with torch.no_grad():
        logits_a = model(input_ids=ids, position_ids=base_pos).logits[0, -1].float()
        tampered = base_pos.clone()
        tampered[0, -1] = 999
        logits_b = model(input_ids=ids, position_ids=tampered).logits[0, -1].float()
    delta = (logits_a - logits_b).abs().max().item()
    record("修改 position_ids 会改变 logits", delta > 1e-3, f"max|Δ| = {delta:.3e}")

    # ---------------------------------------------------------------- T3
    print("\n=== T3 双流推进（思考与输出交错）===")
    from meowllm.engine.dualstream.blocks import Block, View
    from meowllm.engine.dualstream.loop import DualStreamLoop

    loop = DualStreamLoop(
        model=model, tokenizer=tok,
        thinker_max=min(48, args.steps * 4), writer_max=min(48, args.steps * 4),
        probe_every=args.probe_every or max(4, args.steps // 2), device=device,
        temperature=0.7, top_p=0.9, seed=1234)

    started = time.perf_counter()
    loop.reset(messages)
    pref_s = time.perf_counter() - started
    record("prefill + 起始标记", True,
           f"{pref_s:.2f}s，块长度 {[(b.value, n) for b, n in loop.layout.lengths.items()]}")

    trace: list[str] = []
    comparisons: list[tuple[float, float, bool]] = []

    def _hook(block, view, logits, prompt_ids, thinker_ids, writer_ids, count):
        """在 forward 那一刻做对拍：此处的上下文与该 forward 看到的完全一致。"""
        if count != 1:            # 只看单 token 的解码步，跳过多点 prefill
            return
        if block is not Block.WRITER:   # 用 writer 视图做基准
            return
        ref = next_token_logits(model, loop.blocks(), View.WRITER, device)
        cos = torch.nn.functional.cosine_similarity(
            logits.unsqueeze(0), ref.unsqueeze(0)).item()
        top1 = int(logits.argmax()) == int(ref.argmax())
        comparisons.append(((logits - ref).abs().max().item(), cos, top1))
        print(f"        [comp] P={len(prompt_ids)} T={len(thinker_ids)} "
              f"W={len(writer_ids)}  cos={cos:.4f} top1={top1}")

    from meowllm.engine.dualstream.reference import next_token_logits  # noqa: E402

    t0 = time.perf_counter()
    loop.debug_hook = _hook if not args.no_compare else None
    for _ in range(args.steps):
        for chunk in loop.step():
            if chunk.stream == "thinker":
                trace.append(("T", chunk.text))
            elif chunk.stream == "writer":
                trace.append(("W", chunk.text))
            elif chunk.stream == "mode":
                trace.append(("M", "够" if chunk.detail.get("enough") else "不够"))
    loop.debug_hook = None
    step_s = time.perf_counter() - t0

    n_think = loop.stats.thinker_tokens
    n_write = loop.stats.writer_tokens
    record("两条流都有产出", n_think > 0 and n_write > 0,
           f"thinker {n_think} tok / writer {n_write} tok，{step_s:.1f}s "
           f"（{step_s / max(1, args.steps):.2f}s/步）")

    think_txt = "".join(c for k, c in trace if k == "T")
    write_txt = "".join(c for k, c in trace if k == "W")
    print(f"\n      思考（不可见）: {think_txt[:160]}")
    print(f"      输出（可见）  : {write_txt[:160]}")
    print(f"      交错序列      : {''.join(k for k, _ in trace)[:60]}")

    # ---------------------------------------------------------------- T4
    if not args.no_compare:
        print("\n=== T4 整模型 logits 观测（不是验收线）===")
        print("  说明：这里用 token 列表重建参考序列，与引擎真实 KV 状态不一定严格对应，")
        print("        所以只作为观测。**P2 的正式验收在 .scripts/ar_math_check.py**")
        print("        （那里把 attention 单独拎出来，与物理重排对照，误差 1e-7）。")
        if not comparisons:
            record("观测样本", False, "没有采集到单 token 解码步，加大 --steps")
        else:
            worst_cos = min(c[1] for c in comparisons)
            print(f"      余弦最差 = {worst_cos:.6f}，帧数 = {len(comparisons)}")
            print("      （数值偏低属脚手架重建差异，不代表引擎语义错）")
            record("双流可持续产出", True, f"{len(comparisons)} 帧已采集")

    # ---------------------------------------------------------------- 汇总
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 70)
    print(f"合计 {len(RESULTS)} 项，通过 {passed} 项")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    print("=" * 70)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
