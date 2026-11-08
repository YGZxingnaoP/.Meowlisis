# -*- coding: utf-8 -*-
"""分层接口普查：把所有能碰到的接口按层枚举，而不是只看运行中的 mod。

层级：
    L1 主程序插件 SDK      func/toolbox/plugins/sdk.py（PluginContext / ToolboxPlugin）
    L2 系统提示词桥        func/pipeline/system_prompt.py（SystemPromptBridge）
    L3 NapCat / TTS 等能力  func/toolbox/napcat/napcat_core.py + toolbox_tts
    L4 mod 控制台命令      game_mod/ModEntry.cs 里的 helper.ConsoleCommands.Add
    L5 mod 工具注册表      game_mod/Tools.cs 里的 Add("...")（源码静态）
    L6 运行中的 MCP        127.0.0.1:18080/mcp tools/list（真实）
    L7 mod REST 面         127.0.0.1:8765/*
    L8 插件面板 API        127.0.0.1:8760/api/*

输出：%TEMP%/stardew_interface_census.json + 终端分层摘要。

用法：
    runtime\\311\\python.exe -B plugins\\stardew_agent\\tests\\interface_census.py
"""

import argparse
import ast
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(os.environ.get("TEMP", "."), "stardew_interface_census.json")

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ---------- HTTP ----------
def post_json(url, payload, timeout=20):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            return {"error": "http %s" % exc.code}
    except Exception as exc:
        return {"error": str(exc)}


def get_json(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        return {"error": "http %s" % exc.code}
    except Exception as exc:
        return {"error": str(exc)}


# ---------- AST 静态枚举 ----------
def module_path(*parts):
    return os.path.join(ROOT, *parts)


def class_methods(path, class_name):
    """返回类里定义的方法名（不含下划线私有）。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
    except Exception as exc:
        return {"error": str(exc), "methods": []}
    methods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not item.name.startswith("_"):
                        methods.append(item.name)
    return {"methods": sorted(methods), "path": os.path.relpath(path, ROOT)}


def console_commands(path):
    try:
        text = open(path, "r", encoding="utf-8").read()
    except Exception as exc:
        return {"error": str(exc), "commands": []}
    names = []
    marker = 'helper.ConsoleCommands.Add("'
    index = 0
    while True:
        index = text.find(marker, index)
        if index < 0:
            break
        start = index + len(marker)
        end = text.find('"', start)
        if end < 0:
            break
        names.append(text[start:end])
        index = end
    return {"commands": sorted(set(names)), "path": os.path.relpath(path, ROOT)}


def tool_registry(path):
    try:
        text = open(path, "r", encoding="utf-8").read()
    except Exception as exc:
        return {"error": str(exc), "tools": []}
    names = []
    marker = 'Add("'
    index = 0
    while True:
        index = text.find(marker, index)
        if index < 0:
            break
        start = index + len(marker)
        end = text.find('"', start)
        if end < 0:
            break
        name = text[start:end]
        if name and " " not in name:
            names.append(name)
        index = end
    return {"tools": sorted(set(names)), "path": os.path.relpath(path, ROOT)}


# ---------- 运行中的接口 ----------
def census_mcp(port):
    url = "http://127.0.0.1:%d/mcp" % port
    init = post_json(url, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "interface-census", "version": "0.1"}},
    })
    tools = post_json(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    items = ((tools.get("result") or {}).get("tools") or []) if isinstance(tools, dict) else []
    result = []
    for tool in items:
        schema = tool.get("inputSchema") or {}
        result.append({
            "name": tool.get("name"),
            "required": schema.get("required") or [],
            "properties": sorted((schema.get("properties") or {}).keys()),
        })
    return {
        "ok": bool(result),
        "server": ((init.get("result") or {}).get("serverInfo") or {}),
        "protocol": ((init.get("result") or {}).get("protocolVersion")),
        "count": len(result),
        "tools": result,
    }


def census_mod_rest(port):
    base = "http://127.0.0.1:%d" % port
    items = []
    for method, path in (("GET", "/ping"), ("GET", "/state"), ("GET", "/saves"),
                         ("GET", "/screenshot")):
        data = get_json(base + path)
        items.append({"method": method, "path": path,
                      "ok": bool(isinstance(data, dict) and data.get("ok") is not False),
                      "keys": sorted((data or {}).keys())[:10] if isinstance(data, dict) else []})
    for path in ("/command", "/load"):
        data = post_json(base + path, {})
        items.append({"method": "POST", "path": path, "ok": bool(isinstance(data, dict)),
                      "keys": sorted((data or {}).keys())[:10] if isinstance(data, dict) else []})
    return {"base": base, "count": len(items), "items": items}


def census_panel(port):
    base = "http://127.0.0.1:%d" % port
    items = []
    for method, path in (("GET", "/api/state"), ("GET", "/api/agent"), ("GET", "/api/day"),
                         ("GET", "/api/diary"), ("GET", "/api/journal"), ("GET", "/api/memory"),
                         ("GET", "/api/habits"), ("GET", "/api/plans"), ("GET", "/api/todos")):
        data = get_json(base + path)
        items.append({"method": method, "path": path,
                      "ok": bool(isinstance(data, dict) and data.get("ok") is not False),
                      "keys": sorted((data or {}).keys())[:10] if isinstance(data, dict) else []})
    for path in ("/api/request", "/api/play"):
        data = post_json(base + path, {})
        items.append({"method": "POST", "path": path, "ok": bool(isinstance(data, dict)),
                      "keys": sorted((data or {}).keys())[:10] if isinstance(data, dict) else []})
    return {"base": base, "count": len(items), "items": items}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcp", type=int, default=18080)
    parser.add_argument("--mod", type=int, default=8765)
    parser.add_argument("--panel", type=int, default=8760)
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "L1_plugin_sdk": {
            "context": class_methods(module_path("func", "toolbox", "plugins", "sdk.py"), "PluginContext"),
            "plugin_hooks": class_methods(module_path("func", "toolbox", "plugins", "sdk.py"), "ToolboxPlugin"),
            "trigger_tool": class_methods(module_path("func", "toolbox", "plugins", "sdk.py"), "TriggerTool"),
        },
        "L2_system_prompt": class_methods(
            module_path("func", "pipeline", "system_prompt.py"), "SystemPromptBridge"),
        "L3_napcat": class_methods(
            module_path("func", "toolbox", "napcat", "napcat_core.py"), "TBNapCatCore"),
        "L3_tts": class_methods(
            module_path("func", "pipeline", "toolbox_tts.py"), "ToolboxTtsBridge"),
        "L4_mod_console": console_commands(
            module_path("plugins", "stardew_agent", "game_mod", "ModEntry.cs")),
        "L5_mod_tools_static": tool_registry(
            module_path("plugins", "stardew_agent", "game_mod", "Tools.cs")),
        "L6_mcp_live": census_mcp(args.mcp),
        "L7_mod_rest": census_mod_rest(args.mod),
        "L8_panel": census_panel(args.panel),
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    def line(label, value):
        print("%-22s %s" % (label, value))

    l1 = report["L1_plugin_sdk"]
    line("L1 PluginContext", "%d 个方法" % len(l1["context"]["methods"]))
    line("L1 ToolboxPlugin", "%d 个钩子" % len(l1["plugin_hooks"]["methods"]))
    line("L2 SystemPromptBridge", "%d 个方法" % len(report["L2_system_prompt"]["methods"]))
    line("L3 NapCat", "%d 个方法" % len(report["L3_napcat"]["methods"]))
    line("L3 TTS", "%d 个方法" % len(report["L3_tts"]["methods"]))
    line("L4 mod 控制台", "%d 个命令：%s" % (
        len(report["L4_mod_console"]["commands"]), "、".join(report["L4_mod_console"]["commands"])))
    line("L5 mod 工具源码", "%d 个工具" % len(report["L5_mod_tools_static"]["tools"]))
    line("L6 MCP 实际", "%d 个工具" % report["L6_mcp_live"]["count"])
    line("L7 mod REST", "%d 个端点" % report["L7_mod_rest"]["count"])
    line("L8 面板 API", "%d 个端点" % report["L8_panel"]["count"])
    print("\n报告：%s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
