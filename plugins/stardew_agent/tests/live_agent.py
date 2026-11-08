# -*- coding: utf-8 -*-
"""真机实测：通过插件自己的 HTTP API 驱动角色，调真实模型、执行真实游戏动作。

前置：
    1. 游戏已启动并读档（mod 的 /state ready=true）；
    2. 主程序已加载本插件，插件面板在 127.0.0.1:8760。

用法（在项目根目录）：
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\live_agent.py status
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\live_agent.py start
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\live_agent.py ask "去农场把地浇一遍"
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\live_agent.py goal farm_cycle
    runtime\\311\\python.exe plugins\\stardew_agent\\tests\\live_agent.py watch 180

所有请求走的是面板 /api/play、/api/request，和你在网页上点按钮完全同一条路径。
"""

import json
import sys
import time
import urllib.error
import urllib.request

PANEL = "http://127.0.0.1:8760"
MOD = "http://127.0.0.1:8765"

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def http(url, payload=None, timeout=60):
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            return {"ok": False, "reason": "http %s" % exc.code}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def mod_state():
    return http(MOD + "/state", timeout=15)


def panel_state():
    return http(PANEL + "/api/state", timeout=15)


def print_state():
    state = mod_state()
    if not state.get("ready"):
        print("[mod] 还没进存档：%s" % (state.get("reason") or "未读档"))
        return state
    text = str(state.get("text") or "")
    head = [line for line in text.splitlines() if line.strip().startswith((
        "时间：", "金钱：", "技能等级：", "地点：", "你站在"))][:5]
    print("[mod] " + " | ".join(head))
    panel = panel_state()
    agent = panel.get("agent") or {}
    current = agent.get("current") or {}
    print("[插件] 连接=%s 在玩=%s 世界=%s" % (
        agent.get("connected"), agent.get("playing"), agent.get("world_key")))
    print("[插件] 正在：%s · %s" % (
        current.get("title") or current.get("label") or agent.get("activity") or "闲着",
        current.get("progress") or agent.get("thought") or ""))
    plan = panel.get("plan") or {}
    print("[插件] 今日计划：%s" % (plan.get("reason") or plans_summary(plan)))
    return state


def plans_summary(plan):
    nodes = (plan or {}).get("nodes") or []
    if not nodes:
        return "还没定"
    return "；".join(str(node.get("title") or "") for node in nodes[:4])


def wait_ready(seconds=90):
    deadline = time.time() + seconds
    while time.time() < deadline:
        state = mod_state()
        if state.get("ready"):
            return True
        time.sleep(2)
    return False


def watch(seconds=120):
    deadline = time.time() + max(10, int(seconds))
    last = ""
    while time.time() < deadline:
        panel = panel_state()
        agent = panel.get("agent") or {}
        current = agent.get("current") or {}
        line = "在玩=%s 正在=%s %s" % (
            agent.get("playing"), current.get("title") or agent.get("activity") or "闲着",
            current.get("progress") or "")
        if line != last:
            print("[%s] %s" % (time.strftime("%H:%M:%S"), line), flush=True)
            last = line
        for row in (panel.get("journal") or {}).get("items") or []:
            pass
        time.sleep(3)


def main():
    args = sys.argv[1:]
    command = args[0] if args else "status"
    if command == "status":
        print_state()
        return 0
    if command == "wait":
        ok = wait_ready(int(args[1]) if len(args) > 1 else 90)
        print("[mod] 读档完成" if ok else "[mod] 等读档超时")
        return 0 if ok else 1
    if command == "start":
        if not wait_ready(30):
            print("[mod] 游戏还没读档，先读档再开始")
            return 1
        print(http(PANEL + "/api/play", {"action": "start"}))
        time.sleep(3)
        print_state()
        return 0
    if command == "stop":
        print(http(PANEL + "/api/play", {"action": "stop"}))
        return 0
    if command == "pause":
        print(http(PANEL + "/api/play", {"action": "pause"}))
        return 0
    if command == "resume":
        print(http(PANEL + "/api/play", {"action": "resume"}))
        return 0
    if command == "sleep":
        print(http(PANEL + "/api/play", {"action": "sleep"}))
        return 0
    if command == "goal":
        goal = " ".join(args[1:]).strip()
        if not goal:
            print("用法：live_agent.py goal \"想让她做的事\"")
            return 2
        print(http(PANEL + "/api/play", {"action": "grant", "goal": goal}, timeout=120))
        return 0
    if command == "ask":
        text = " ".join(args[1:]).strip()
        if not text:
            print("用法：live_agent.py ask \"想让她做的事\"")
            return 2
        print("发送：" + text)
        result = http(PANEL + "/api/request", {"text": text}, timeout=180)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if command == "watch":
        watch(int(args[1]) if len(args) > 1 else 120)
        return 0
    if command == "probe":
        # 完整真机链路：读档 → 开始玩 → 观察一段 → 状态
        if not wait_ready(60):
            print("[mod] 未读档，退出")
            return 1
        print(http(PANEL + "/api/play", {"action": "start"}))
        watch(int(args[1]) if len(args) > 1 else 120)
        print_state()
        return 0
    print("未知命令：%s" % command)
    return 2


if __name__ == "__main__":
    sys.exit(main())
