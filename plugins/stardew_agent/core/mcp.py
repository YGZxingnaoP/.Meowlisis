# -*- coding: utf-8 -*-
"""模组 MCP 客户端：和参考项目 lib/index.js 的 mcpCall 同一套协议。

只做三件事：
    initialize   拿操作规则（instructions）
    tools/list   拿 52 个动作的 schema
    tools/call   执行任意动作（长动作用 REST 更省事，这里主要给 get_state/get_guide）

协议是 MCP Streamable HTTP；模组在 Accept 里看到 text/event-stream 时会用 SSE
回复（动作期间每 15 秒一行心跳），其余用普通 JSON。两种都解析。
"""

import json
import re
import time
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:18080/mcp"


class McpError(RuntimeError):
    pass


def parse_sse(text):
    """从 SSE 文本里取出 JSON-RPC 回复（忽略 : keep-alive 之类的注释行）。"""
    for block in re.split(r"\r?\n\r?\n", text or ""):
        data = "\n".join(
            line[5:].lstrip()
            for line in block.splitlines()
            if line.startswith("data:")
        )
        if not data:
            continue
        try:
            message = json.loads(data)
        except Exception:
            continue
        if isinstance(message, dict) and ("result" in message or "error" in message):
            return message
    raise McpError("游戏的回复里没有结果（连接可能中途断了）")


def _params_text(schema):
    """把 JSON Schema 的参数压成 x, y?, names... 这种短形式。"""
    schema = schema or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    parts = []
    for key in props:
        parts.append(key if key in required else key + "?")
    return ", ".join(parts)


def help_text(instructions, tools):
    """参考项目 helpText() 的同款内容：规则 + 精简动作列表。

    模组 initialize 的 instructions 里带着整份攻略；第一次 help 先去掉攻略正文，
    要看再用 get_guide 按需读，省上下文。
    """
    rules = instructions or ""
    guide_start = rules.find("## 游戏常识")
    mcp_notes = rules.find("## 通过 MCP 玩的额外说明")
    if guide_start >= 0 and mcp_notes > guide_start:
        rules = rules[:guide_start] + rules[mcp_notes:]

    lines = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        params = _params_text(tool.get("inputSchema"))
        summary = str(tool.get("description") or "").split("\n")[0]
        for sep in ("。", "."):
            if sep in summary:
                summary = summary.split(sep)[0]
                break
        lines.append("- %s(%s)：%s" % (tool.get("name") or "?", params, summary))

    return "\n".join([
        "# 用 stardew 工具玩星露谷",
        "下面每个“动作”都通过 stardew 工具调用：action 填动作名，args 填参数对象。",
        '例如 {"action":"move_to","args":{"x":64,"y":15}}，{"action":"water_crops"}。',
        "参数后面带 ? 的可以不填。",
        "",
        rules.strip(),
        "",
        "## 全部动作（%d 个；不确定参数就先按名字猜，失败信息会告诉你哪里不对）" % len(lines),
        *lines,
    ]).strip()


class Mcp:
    def __init__(self, url=DEFAULT_URL, timeout=10.0):
        self.url = str(url or "").strip() or DEFAULT_URL
        self.timeout = float(timeout or 10.0)
        self._next_id = 0
        self._tools = None
        self._tools_at = 0.0

    # ---------- 底层 ----------
    def _rpc(self, method, params=None, timeout=None):
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params or {},
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
                ctype = response.headers.get("Content-Type") or ""
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            raise McpError("MCP HTTP %s %s" % (exc.code, body))
        except urllib.error.URLError as exc:
            raise McpError("连不上游戏的 MCP：%s" % (getattr(exc, "reason", exc),))
        except Exception as exc:
            raise McpError(str(exc))

        if "text/event-stream" in ctype:
            message = parse_sse(raw)
        else:
            try:
                message = json.loads(raw) if raw.strip() else {}
            except Exception as exc:
                raise McpError("MCP 返回的不是 JSON：%s" % exc)

        if not isinstance(message, dict):
            raise McpError("MCP 返回格式不对")
        if message.get("error"):
            error = message["error"]
            if isinstance(error, dict):
                raise McpError(str(error.get("message") or error.get("code") or error))
            raise McpError(str(error))
        return message.get("result") or {}

    # ---------- 对外 ----------
    def initialize(self):
        return self._rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "meowlisis-stardew", "version": "1"},
        })

    def tools(self, refresh=False):
        now = time.time()
        if self._tools is not None and not refresh and now - self._tools_at < 60:
            return self._tools
        result = self._rpc("tools/list", {})
        self._tools = list(result.get("tools") or [])
        self._tools_at = now
        return self._tools

    def call(self, name, arguments=None, timeout=None):
        result = self._rpc("tools/call", {
            "name": str(name or ""),
            "arguments": arguments if isinstance(arguments, dict) else {},
        }, timeout=timeout)
        content = result.get("content") or []
        text = "\n".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
        if not text:
            raise McpError("游戏没有返回内容")
        return text

    def help(self):
        init = self.initialize()
        return help_text(init.get("instructions") or "", self.tools())
