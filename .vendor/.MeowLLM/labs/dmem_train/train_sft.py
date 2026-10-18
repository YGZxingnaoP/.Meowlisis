# -*- coding: utf-8 -*-
"""δ-mem 的 SFT 训练：只训 δ-mem，backbone 冻结（论文 §3.6）。

为什么单独放在 labs/dmem_train/
-------------------------------
训练要 torch + transformers + 一块能塞下两次前向的显卡；而 MeowLLM 的运行时
（`.vendor/.MeowLLM/meowllm`）是"加载即用"的推理代码。两者混在一起会让推理侧
平白多出数据、优化器、checkpoint 这些依赖。所以：

    labs/dmem_train/   训（可搬到云上跑）
    meowllm/dmem/      推理侧模块（引擎加载它）

两边共用同一份 `DeltaMem` 实现，训练产物是 `.safetensors` 权重 + 每用户状态 `.pt`。

前向两趟
--------
    趟 1  model(context)          采每层隐状态 -> chunk 递推 -> S_C
    趟 2  model(query+response)   输入里**没有** context，只靠 S_C 修正 attention
    loss  = CE(response)

用法
----
    # 干跑（2 步，查形状/loss/显存）
    python train_sft.py --data data/sft.jsonl --dry-run

    # 正式（r=64 全层，单卡 24~32G 建议 context 2048、accum 8）
    python train_sft.py --data data/sft.jsonl --preset presets/r64.yaml
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time

import torch
import torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_ROOT = os.path.dirname(os.path.dirname(HERE))          # .vendor/.MeowLLM
if MODULE_ROOT not in sys.path:
    sys.path.insert(0, MODULE_ROOT)
sys.path.insert(0, HERE)

from dataset import (dataset_stats, encode_sample, read_jsonl,  # noqa: E402
                     split_rows)

from meowllm.dmem import DeltaMem, DeltaMemConfig  # noqa: E402


def lr_at(step: int, total: int, base: float, warmup: float) -> float:
    warm = max(1, int(total * warmup))
    if step < warm:
        return base * (step + 1) / warm
    progress = (step - warm) / max(1, total - warm)
    return base * 0.5 * (1.0 + math.cos(math.pi * progress))


def parse_layers(text: str) -> tuple:
    text = str(text or "").strip()
    if not text:
        return ()
    if "-" in text:
        lo, hi = text.split("-", 1)
        return tuple(range(int(lo), int(hi) + 1))
    return tuple(int(x) for x in text.split(",") if x.strip())


def load_preset(args) -> None:
    """预设文件里的键只在命令行没显式给的时候生效。"""
    if not args.preset:
        return
    import yaml

    with open(args.preset, "r", encoding="utf-8") as fh:
        preset = (yaml.safe_load(fh) or {}).get("dmem") or {}
    explicit = set()
    for token in sys.argv[1:]:
        if token.startswith("--"):
            explicit.add(token[2:].split("=")[0].replace("-", "_"))
    for key, value in preset.items():
        name = str(key).replace("-", "_")
        if name in explicit or not hasattr(args, name):
            continue
        setattr(args, name, value)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "data", "sft.jsonl"))
    ap.add_argument("--model", default=os.path.join(MODULE_ROOT, "models", "Qwen3-0.6B"))
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--preset", default="")
    ap.add_argument("--rank", type=int, default=64)
    ap.add_argument("--n-states", dest="n_states", type=int, default=1)
    ap.add_argument("--chunk", type=int, default=16)
    ap.add_argument("--alpha", type=float, default=16.0)
    ap.add_argument("--layers", default="",
                    help="插入层：空=全层，8-19=中间 12 层，0,5,9=指定层")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--warmup", type=float, default=0.1)
    ap.add_argument("--weight-decay", dest="weight_decay", type=float, default=0.0)
    ap.add_argument("--context-len", dest="context_len", type=int, default=1024)
    ap.add_argument("--answer-len", dest="answer_len", type=int, default=256)
    ap.add_argument("--window", type=int, default=1024, help="写记忆的前向窗口")
    ap.add_argument("--clip", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-steps", dest="max_steps", type=int, default=0)
    ap.add_argument("--holdout", type=float, default=0.05)
    ap.add_argument("--save-every", dest="save_every", type=int, default=200)
    ap.add_argument("--dry-run", dest="dry_run", action="store_true")
    return ap


class Telemetry:
    """给前端（webui.py）读的训练指标：一行一步的 jsonl + 一份状态 json。

    为什么不用 TensorBoard：前端要跑在 AutoDL 上被人肉监控，多一个依赖就多一个坑。
    两个文件就够画曲线，而且崩了也能 `tail -f` 看。
    """

    def __init__(self, out_dir: str, total_steps: int, rows: int, argv: list[str]) -> None:
        self.dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.metrics_path = os.path.join(out_dir, "metrics.jsonl")
        self.status_path = os.path.join(out_dir, "status.json")
        self.total = int(total_steps)
        self.rows = int(rows)
        self.started = time.time()
        self._last = {"loss": None, "lr": None, "step": 0}
        # 上一轮留下的曲线不要混进来
        try:
            os.remove(self.metrics_path)
        except OSError:
            pass
        self.write_status(state="running", phase="init", argv=argv)

    def log_step(self, step: int, loss: float, lr: float,
                 extra: dict | None = None) -> None:
        now = time.time()
        row = {
            "t": round(now - self.started, 2),
            "step": int(step),
            "total": self.total,
            "loss": round(float(loss), 5),
            "lr": float(lr),
            "samples": int(step * 1),
            **({"extra": extra} if extra else {}),
        }
        with open(self.metrics_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._last = {"loss": float(loss), "lr": float(lr), "step": int(step)}
        self.write_status(state="running", phase="train")

    def write_status(self, state: str = "running", phase: str = "train",
                     argv: list[str] | None = None, **extra) -> None:
        elapsed = time.time() - self.started
        step = int(self._last.get("step") or 0)
        eta = None
        if step > 0 and self.total > step:
            eta = round(elapsed / step * (self.total - step), 1)
        body = {
            "state": state,
            "phase": phase,
            "step": step,
            "total": self.total,
            "progress": round(step / self.total, 4) if self.total else 0.0,
            "loss": self._last.get("loss"),
            "lr": self._last.get("lr"),
            "rows": self.rows,
            "elapsed_s": round(elapsed, 1),
            "eta_s": eta,
            "pid": os.getpid(),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            **extra,
        }
        if argv is not None:
            body["argv"] = argv
        tmp = self.status_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(body, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.status_path)

    def finish(self, state: str = "finished", **extra) -> None:
        self.write_status(state=state, phase="done", **extra)


def evaluate(model, dmem, tok, rows, args, device) -> dict:
    """留出集：同一批样本，分别在"有状态/无状态"下算 response 的 NLL。

    这是论文 §5.1 的最小复刻：差值就是"状态里到底有没有信息"。
    """
    dmem.eval()
    out = {}
    for tag, use_state in (("no_context", False), ("with_state", True)):
        total, tokens = 0.0, 0
        for row in rows:
            enc = encode_sample(tok, row, args.context_len, args.answer_len)
            if not enc.ctx_ids or enc.answer_len == 0:
                continue
            if use_state:
                dmem.write_state(model, enc.ctx_ids, device=device)
            else:
                dmem.clear_state()
            ids = torch.tensor([enc.input_ids], dtype=torch.long, device=device)
            lab = torch.tensor([enc.labels], dtype=torch.long, device=device)
            with torch.no_grad(), dmem.steering(use_state):
                logits = model(input_ids=ids, use_cache=False).logits[0, :-1].float()
            total += F.cross_entropy(logits, lab[0, 1:], ignore_index=-100,
                                     reduction="sum").item()
            tokens += int((lab[0, 1:] != -100).sum())
        out[tag] = round(total / max(1, tokens), 4)
    out["gap"] = round(out["no_context"] - out["with_state"], 4)
    dmem.train()
    return out


def main() -> int:
    args = build_parser().parse_args()
    load_preset(args)

    # 卡死诊断：设了 DMEM_DUMP_STACK=<秒> 就定期把所有线程的调用栈打到 stderr。
    # 训练"进程还在但 step 不动"时，这个能直接指出卡在哪一行。
    _dump = os.environ.get("DMEM_DUMP_STACK")
    if _dump:
        import faulthandler

        faulthandler.dump_traceback_later(int(_dump), repeat=True)
        print(f"[diag] faulthandler 每 {_dump}s dump 一次调用栈", flush=True)

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32

    rows = read_jsonl(args.data)
    if not rows:
        print(f"数据为空：{args.data}（先跑 build_data.py）")
        return 1
    train, holdout = split_rows(rows, args.holdout, args.seed)
    print(f"样本 {len(rows)}：训练 {len(train)}，留出 {len(holdout)}")

    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.model)
    stats = dataset_stats(rows, tok, args.context_len, args.answer_len)
    print(f"数据画像：context p50={stats['context_tokens_p50']} "
          f"max={stats['context_tokens_max']}；answer p50={stats['answer_tokens_p50']}；"
          f"来源 {stats['sources']}")

    model = AutoModelForCausalLM.from_pretrained(
        args.model, dtype=dtype, device_map=device if device == "cuda" else None)
    model.config.use_cache = False

    cfg = DeltaMemConfig(rank=args.rank, n_states=args.n_states, chunk=args.chunk,
                         alpha=args.alpha, layers=parse_layers(args.layers),
                         window=args.window)
    dmem = DeltaMem(cfg)
    info = dmem.attach(model)
    frozen = dmem.freeze_backbone(model)      # 论文：φ 全程不动
    report = dmem.finetune_report()
    print(f"δ-mem：{len(info['layers'])} 层 r={cfg.rank} N={cfg.n_states} "
          f"chunk={cfg.chunk} -> {report['trainable'] / 1e6:.2f}M 可训参数")
    print(f"已冻结 backbone 张量 {frozen} 个；参数组 {report['groups']}")

    params = dmem.trainable_parameters()
    optim = torch.optim.AdamW(params, lr=args.lr, betas=(0.9, 0.95),
                              weight_decay=args.weight_decay)
    total_steps = max(1, int(len(train) * args.epochs / max(1, args.accum)))
    if args.max_steps:
        total_steps = min(total_steps, args.max_steps)
    print(f"计划 {total_steps} 个优化步（accum={args.accum}, lr={args.lr}）")

    os.makedirs(args.out, exist_ok=True)
    tele = Telemetry(args.out, total_steps, len(rows), sys.argv[1:])
    tele.write_status(state="running", phase="train",
                      data=os.path.basename(args.data), **{
                          "rank": cfg.rank, "n_states": cfg.n_states,
                          "chunk": cfg.chunk, "layers": args.layers or "all",
                          "params_m": round(report["trainable"] / 1e6, 2),
                          "dataset": stats,
                      })
    step, micro, running = 0, 0, 0.0
    started = time.perf_counter()
    dmem.train()
    stop = False
    for epoch in range(max(1, int(math.ceil(args.epochs)))):
        random.shuffle(train)
        for row in train:
            enc = encode_sample(tok, row, args.context_len, args.answer_len)
            if not enc.ctx_ids or enc.answer_len == 0 or len(enc.input_ids) < 2:
                continue
            ids = torch.tensor([enc.input_ids], dtype=torch.long, device=device)
            lab = torch.tensor([enc.labels], dtype=torch.long, device=device)

            dmem.zero_grad(set_to_none=True)
            # 趟 1：写记忆（保图 -> 写投影有梯度）
            dmem.write_state(model, enc.ctx_ids, device=device, keep_graph=True)
            # 趟 2：steering 前向，context 不在输入里
            with dmem.steering(True):
                logits = model(input_ids=ids, use_cache=False).logits[0, :-1].float()
            loss = F.cross_entropy(logits, lab[0, 1:], ignore_index=-100)
            (loss / args.accum).backward()
            running += loss.item()
            micro += 1

            if micro % args.accum:
                continue
            torch.nn.utils.clip_grad_norm_(params, args.clip)
            for group in optim.param_groups:
                group["lr"] = lr_at(step, total_steps, args.lr, args.warmup)
            optim.step()
            step += 1
            tele.log_step(step, running / args.accum,
                          optim.param_groups[0]["lr"],
                          extra={"elapsed": round(time.perf_counter() - started, 1),
                                 "peak_gib": (round(torch.cuda.max_memory_allocated() / 2**30, 2)
                                              if device == "cuda" else None)})
            if step % 10 == 0 or args.dry_run:
                vram = (f" peak={torch.cuda.max_memory_allocated() / 2**30:.2f}G"
                        if device == "cuda" else "")
                print(f"  step {step}/{total_steps} loss={running / args.accum:.4f} "
                      f"lr={optim.param_groups[0]['lr']:.2e} "
                      f"{time.perf_counter() - started:.0f}s{vram}", flush=True)
            running = 0.0
            if step % args.save_every == 0:
                dmem.save(os.path.join(args.out, "dmem.step.safetensors"),
                          meta={"step": step})
            if args.dry_run and step >= 2:
                stop = True
                break
            if args.max_steps and step >= args.max_steps:
                stop = True
                break
        if stop:
            break

    weight_path = os.path.join(args.out, "dmem.safetensors")
    meta = {"train_rows": len(train), "steps": step, "dry_run": args.dry_run,
            "data": os.path.basename(args.data)}
    dmem.save(weight_path, meta=meta)
    print(f"权重已存：{weight_path}")
    tele.write_status(state="running", phase="eval",
                      weights=os.path.basename(weight_path))

    if holdout:
        print("留出集（response NLL/token，越低越好）：")
        result = evaluate(model, dmem, tok, holdout, args, device)
        print(f"  no-context {result['no_context']:.4f}  "
              f"with-state {result['with_state']:.4f}  "
              f"gap {result['gap']:.4f}")
        with open(os.path.join(args.out, "eval.json"), "w", encoding="utf-8") as fh:
            json.dump({"step": step, **result, "meta": meta}, fh,
                      ensure_ascii=False, indent=2)
        tele.finish(eval=result, weights=os.path.basename(weight_path))
    else:
        tele.finish()
    return 0


def _guess_out(argv: list[str]) -> str:
    for i, token in enumerate(argv):
        if token == "--out" and i + 1 < len(argv):
            return argv[i + 1]
        if token.startswith("--out="):
            return token.split("=", 1)[1]
    return os.path.join(HERE, "out")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:                     # noqa: BLE001 - 崩了也要给前端留状态
        import traceback

        traceback.print_exc()
        out = _guess_out(sys.argv[1:])
        try:
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, "status.json"), "w", encoding="utf-8") as fh:
                json.dump({"state": "error", "phase": "crash",
                           "error": traceback.format_exc()[-4000:],
                           "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                          fh, ensure_ascii=False, indent=2)
        except Exception:                     # noqa: BLE001
            pass
        raise SystemExit(1)
