# -*- coding: utf-8 -*-
"""检查插件源码单文件行数；超过 800 行直接失败。

用法：
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\line_limit.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 800
SUFFIXES = (".py", ".cs", ".js", ".css", ".html")


def main():
    bad = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [name for name in dirs
                   if name not in ("__pycache__", "bin", "obj", "dist", "node_modules")]
        for name in files:
            if not name.endswith(SUFFIXES):
                continue
            path = os.path.join(base, name)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    lines = sum(1 for _ in handle)
            except OSError:
                continue
            if lines > LIMIT:
                bad.append((lines, path))
    for lines, path in sorted(bad, reverse=True):
        print("%5d  %s" % (lines, os.path.relpath(path, ROOT)))
    if bad:
        print("\nFAIL: %d 个文件超过 %d 行" % (len(bad), LIMIT))
        return 1
    print("OK: 所有源码文件 <= %d 行" % LIMIT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
