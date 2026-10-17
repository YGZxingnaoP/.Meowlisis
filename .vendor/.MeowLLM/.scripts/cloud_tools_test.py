# -*- coding: utf-8 -*-
"""云端 tools 协议端到端测试（跑在云上，用 requests 打本地服务）。"""
import json
import sys
import time
import urllib.request

URL = "http://127.0.0.1:18100/meowllm/v1/chat/completions"
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的天气",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名"}},
            "required": ["city"],
        },
    },
}]


def post(body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(URL, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode())


def wait_ready(timeout=300) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:18100/meowllm/control/health", timeout=3) as r:
                if json.loads(r.read().decode()).get("ready"):
                    print(f"[ready] {time.time() - t0:.0f}s")
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(4)
    return False


def main() -> int:
    if not wait_ready():
        print("[fail] 服务没就绪")
        return 1

    print("\n=== 1) 不带 tools（普通对话）===")
    r = post({"model": "meowllm-local",
              "messages": [{"role": "user", "content": "用一句话介绍你自己"}],
              "max_tokens": 64})
    msg = r["choices"][0]["message"]
    print("finish_reason:", r["choices"][0].get("finish_reason"))
    print("content:", (msg.get("content") or "")[:120])

    print("\n=== 2) 带 tools（应返回 tool_calls）===")
    r = post({"model": "meowllm-local",
              "messages": [{"role": "user", "content": "上海今天天气怎么样？"}],
              "tools": TOOLS,
              "max_tokens": 256})
    choice = r["choices"][0]
    print("finish_reason:", choice.get("finish_reason"))
    msg = choice["message"]
    print("content:", (msg.get("content") or "")[:120])
    calls = msg.get("tool_calls") or []
    print("tool_calls:", json.dumps(calls, ensure_ascii=False)[:400])

    ok = choice.get("finish_reason") == "tool_calls" and bool(calls)
    print("\n结论:", "PASS ✓ tools 协议通了" if ok else "FAIL ✗ 没拿到 tool_calls")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
