# -*- coding: utf-8 -*-
"""两天真机脚本（新执行层的薄封装）。

旧版直接调用 mod 的 /command 技能名，移植后执行层换成了 MCP 工具，
所以这里改为调用 tests/live_agent.py 的真机链路：
    读档 → 开始玩 → 观察 → 输出状态。

用法（游戏已启动并读档）：
    runtime\\311\\python.exe -B plugins\\stardew_agent\\tests\\two_day_play.py
    runtime\\311\\python.exe -B plugins\\stardew_agent\\tests\\two_day_play.py 300
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRIPT = os.path.join(ROOT, "plugins", "stardew_agent", "tests", "live_agent.py")


def main():
    seconds = sys.argv[1] if len(sys.argv) > 1 else "180"
    print("真机链路：读档 → 开始玩 → 观察 %s 秒 → 状态" % seconds)
    result = subprocess.run([sys.executable, "-B", SCRIPT, "probe", str(seconds)])
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
