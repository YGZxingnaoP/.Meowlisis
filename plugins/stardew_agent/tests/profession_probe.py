# -*- coding: utf-8 -*-
"""职业选择探针：游戏里出现 5/10 级职业菜单时，用它查看/选择。

用法：
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\profession_probe.py
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\profession_probe.py --choose 0
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from plugins.stardew_agent.core.bridge import Bridge  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--choose", type=int, default=-1,
                        help="候选下标；-1 只看不选")
    args = parser.parse_args()
    bridge = Bridge(args.url, 5)
    state = bridge.state()
    pending = (state.get("player") or {}).get("pending_profession")
    print("pending_profession:", json.dumps(pending, ensure_ascii=False, indent=2), flush=True)
    if not pending:
        print("现在没有职业选择菜单（先升级到 5/10 级）", flush=True)
        return 0
    if args.choose < 0:
        return 0
    choices = pending.get("choices") or []
    if args.choose >= len(choices):
        print("下标越界，候选只有 %d 个" % len(choices), flush=True)
        return 1
    result = bridge.call("choose_profession", side=args.choose, timeout=60)
    print("choose:", json.dumps(result, ensure_ascii=False, indent=2)[:2000], flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
