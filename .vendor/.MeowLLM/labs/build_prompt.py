# -*- coding: utf-8 -*-
"""主项目提示词构建（只读模式：**不写短期记忆**）。

给实验台（labs）用：按主项目真实链路拼出一条完整的 messages，
但把 ShortMemory 的所有写入口都打桩成空 —— 测试不会往
`.temp/public_short_mem.json` 里留任何东西。

用法（任意目录）：
    python labs/build_prompt.py --uid 000001 --text "在吗"
    python labs/build_prompt.py --uid 000001 --text "在吗" --history 12 --out req.json

输出（stdout 一行 JSON）：
    {"messages": [...], "system_chars": 5123, "history_rounds": 12,
     "memory_sha1_before": "...", "memory_sha1_after": "...", "memory_unchanged": true}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # .../labs
MODULE_ROOT = os.path.dirname(HERE)                        # .../.MeowLLM
PROJECT_ROOT = os.path.dirname(os.path.dirname(MODULE_ROOT))
MEM_PATH = os.path.join(PROJECT_ROOT, ".temp", "public_short_mem.json")

#: ⚠ 必须锁死 UTF-8：被别的进程用管道读走时，Python 默认用控制台代码页
#: （中文 Windows = cp936/GBK）。GBK 的 JSON 再按 UTF-8 解就是满屏乱码
#: —— 模型收到乱码 system 后也会跟着吐乱码（实测"ɶ����Ϣ…"）。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - 老解释器没有 reconfigure
    pass


def _null_log() -> None:
    """把主项目的文件日志打桩：实验台不需要写 logs/（也让脚本能在只读环境跑）。"""
    import logging

    import func.log.default_log as dl

    class _NullDefaultLog:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401
            pass

        def getLogger(self):
            return logging.getLogger("lab.null")

    dl.DefaultLog = _NullDefaultLog  # type: ignore[assignment]


def _freeze_memory() -> None:
    """ShortMemory 的构造本身会写「会话分割」标记 —— 全部打桩成空。"""
    import func.pipeline.short_memory as sm

    def _noop(*_args, **_kwargs) -> None:
        return None

    sm.ShortMemory._mark_session = _noop  # type: ignore[assignment]
    sm.ShortMemory._write = _noop         # type: ignore[assignment]
    sm.ShortMemory.save = _noop           # type: ignore[assignment]


def _sha1(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()
    except OSError:
        return ""


def _read_history(limit: int) -> list[dict]:
    """直接读 JSON，不经过 ShortMemory（避免 _mark_session 写入）。"""
    try:
        with open(MEM_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    rows = [{"role": m["role"], "content": m["content"]}
            for m in data if isinstance(m, dict) and m.get("role") and m.get("content")]
    return rows[-limit:] if limit > 0 else rows


def build(uid: str, text: str, history_limit: int) -> dict:
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    os.chdir(PROJECT_ROOT)

    before = _sha1(MEM_PATH)
    _null_log()
    _freeze_memory()

    from func.catbrain.prompt_builder import MeowPromptBuilder
    from func.llm.prompt_get import PromptGet
    from func.pipeline.system_prompt import SystemPromptBridge

    # 主进程（api.py:73）启动时做的就是这一步；不注册的话 system 里没有人设正文，
    # 只剩前置词 + 后置词（实测只有 300 字左右）。
    SystemPromptBridge().register_builder(MeowPromptBuilder())

    system = PromptGet().get_system_prompt(uid, text) or ""
    history = _read_history(history_limit)
    messages = ([{"role": "system", "content": system}] + history
                + [{"role": "user", "content": text}])
    after = _sha1(MEM_PATH)
    return {
        "messages": messages,
        "system_chars": len(system),
        "history_rounds": len(history),
        "memory_sha1_before": before,
        "memory_sha1_after": after,
        "memory_unchanged": before == after,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uid", default="000001")
    ap.add_argument("--text", required=True)
    ap.add_argument("--history", type=int, default=20, help="取最近多少条历史（0=全部）")
    ap.add_argument("--out", default="", help="把完整的 messages 写进这个文件")
    ap.add_argument("--full", action="store_true", help="stdout 输出完整对象（含 messages）")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args(argv)

    result = build(args.uid, args.text, args.history)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result["messages"], fh, ensure_ascii=False, indent=2)
    if args.full:
        out = {"messages": result["messages"], "system_chars": result["system_chars"],
               "history_rounds": result["history_rounds"],
               "memory_unchanged": result["memory_unchanged"]}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    brief = {k: v for k, v in result.items() if k != "messages"}
    brief["messages"] = len(result["messages"])
    print(json.dumps(brief, ensure_ascii=False,
                     indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
