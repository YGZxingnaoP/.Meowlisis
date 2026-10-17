# -*- coding: utf-8 -*-
"""把引擎包 `dualstream` 改名为 `dualstream`，并重写所有引用。

为什么改
--------
`dualstream` 想表达"用 HuggingFace transformers 的引擎"，但这是实现细节：
真正的内容是**双流异步推理**（一份 KV、两套位置编号）。而且和 HF 的耦合已经
只剩 `compat.py` 一个文件。所以改成 `dualstream`。

同时改的引擎 kind 字符串：`dualstream` -> `dualstream`
（配置里的 `engine.kind`、`safety.allow_engine`、factory 注册都要一起改，
否则会报"未知引擎"）

怎么跑
------
    ..\\..\\runtime\\311\\python.exe .scripts\\rename_dualstream.py --dry-run
    ..\\..\\runtime\\311\\python.exe .scripts\\rename_dualstream.py

跑完请自己验证：
    ..\\..\\runtime\\311\\python.exe .scripts\\ar_p1_smoke.py --steps 10
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # .vendor/.MeowLLM
PKG = ROOT / "meowllm"
OLD_DIR = PKG / "engine" / "dualstream"
NEW_DIR = PKG / "engine" / "dualstream"

OLD_KIND = "dualstream"
NEW_KIND = "dualstream"

#: 需要重写引用的文件类型
TEXT_EXT = {".py", ".yml", ".yaml", ".json", ".md", ".js", ".html", ".bat"}
SKIP_DIRS = {".test", "models", "bags", "llama.cpp", "__pycache__", ".git"}

#: 文件名层面的建议（只报告，不自动改，避免误伤）
NAME_NOTES = [
    ("engine/dualstream/", "engine/dualstream/", "包名：HF 是实现细节，双流才是本质"),
    ("engine/dualstream/mode.py", "engine/dualstream/mode.py",
     "mode 太泛；实际是模式切换判据，可考虑 mode_switch.py"),
    ("tools/parse.py", "tools/tool_calls.py",
     "parse 太泛；实际只做 tool call 抽取"),
    ("engine/llamacpp.py", "(保留)",
     "llama.cpp 二进制已删但后端代码留着，名字仍然正确"),
]


def iter_text_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_EXT:
            out.append(path)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not OLD_DIR.is_dir():
        print(f"[skip] {OLD_DIR} 不存在（可能已经改过了）")
    print(f"目录：{OLD_DIR.name} -> {NEW_DIR.name}")
    print(f"kind：{OLD_KIND} -> {NEW_KIND}")
    print()

    # ---------- 1) 收集要改的文件 ----------
    todo: list[tuple[Path, str]] = []
    for path in iter_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if OLD_KIND not in text:
            continue
        new_text = text.replace(OLD_KIND, NEW_KIND)
        todo.append((path, new_text))

    for path, _ in todo:
        print(f"  改写 {path.relative_to(ROOT)}")
    print(f"\n共 {len(todo)} 个文件需要改")
    print()

    # ---------- 2) 文件名建议（只报告）----------
    print("文件名检查（这些需要人工判断，脚本不自动改）：")
    for old, new, why in NAME_NOTES:
        print(f"  {old:<28} -> {new:<28} {why}")

    if args.dry_run:
        print("\n--dry-run：没有做任何修改")
        return 0

    # ---------- 3) 改内容（先改内容再搬目录，避免路径失效）----------
    for path, new_text in todo:
        path.write_text(new_text, encoding="utf-8")
    print(f"\n已改写 {len(todo)} 个文件")

    # ---------- 4) 搬目录 ----------
    if OLD_DIR.is_dir():
        if NEW_DIR.exists():
            print(f"[warn] {NEW_DIR} 已存在，先删掉旧的再继续")
            return 1
        shutil.move(str(OLD_DIR), str(NEW_DIR))
        print(f"目录已改名：{OLD_DIR.name} -> {NEW_DIR.name}")

    # ---------- 5) 清理 __pycache__ ----------
    for pc in PKG.rglob("__pycache__"):
        shutil.rmtree(pc, ignore_errors=True)
    print("已清理 __pycache__")
    print("\n完成。请验证：")
    print("  ..\\..\\runtime\\311\\python.exe .scripts\\ar_p1_smoke.py --steps 10")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
