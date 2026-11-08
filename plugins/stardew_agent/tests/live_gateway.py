# -*- coding: utf-8 -*-
"""真机接口检查：不依赖旧的 Python Agent/planner。

用法（游戏已启动并读档）：
    runtime\\311\\python.exe -B plugins\\stardew_agent\\tests\\live_gateway.py
    runtime\\311\\python.exe -B plugins\\stardew_agent\\tests\\live_gateway.py --action move_to --args "{\"x\":64,\"y\":15}"

检查：
    REST /ping /state /command
    MCP initialize / tools/list / get_state / get_guide
"""

import argparse
import json
import urllib.error
import urllib.request

REST = "http://127.0.0.1:8765"
MCP = "http://127.0.0.1:18080/mcp"


def request(url, payload=None, timeout=30):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8", "replace")
        ctype = response.headers.get("Content-Type") or ""
    if "text/event-stream" in ctype:
        for block in raw.replace("\r\n", "\n").split("\n\n"):
            data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
            if data:
                message = json.loads(data)
                if "result" in message or "error" in message:
                    return message
        raise RuntimeError("SSE 里没有结果")
    return json.loads(raw) if raw.strip() else {}


def mcp(method, params=None):
    message = request(MCP, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    if message.get("error"):
        raise RuntimeError(str(message["error"]))
    return message.get("result") or {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", default="", help="额外执行一个 REST 动作")
    parser.add_argument("--args", default="{}", help="动作参数 JSON")
    args = parser.parse_args()

    print("ping:", request(REST + "/ping", timeout=5))
    state = request(REST + "/state", timeout=15)
    print("state:", state.get("ready"), str(state.get("text") or "")[:120].replace("\n", " | "))

    init = mcp("initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "live-gateway", "version": "1"},
    })
    print("mcp:", init.get("serverInfo"), "instructions:", len(init.get("instructions") or ""))
    tools = mcp("tools/list").get("tools") or []
    print("tools:", len(tools), ", ".join(t.get("name") or "" for t in tools[:12]), "...")

    print("get_state:", str(mcp("tools/call", {"name": "get_state", "arguments": {}}).get("content"))[:160])
    print("get_guide:", str(mcp("tools/call", {"name": "get_guide", "arguments": {"topic": ""}}).get("content"))[:160])

    if args.action:
        result = request(REST + "/command", {
            "tool": args.action,
            "args": json.loads(args.args or "{}"),
        }, timeout=300)
        print("action:", args.action, result)


if __name__ == "__main__":
    main()
