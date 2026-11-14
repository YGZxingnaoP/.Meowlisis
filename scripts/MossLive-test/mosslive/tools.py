# -*- coding: utf-8 -*-
# scripts/MossLive-test/mosslive/tools.py
# 前台自定义工具：由本进程执行，通过 conversation.item.create 回传结果。
# 本轮只做工具调用本身，不接短期记忆/长期记忆。
#
# 工具：
#   get_time         查本机/指定时区时间         sync
#   open_url         默认浏览器打开网址          sync（有副作用）
#   list_windows     列出可见窗口               sync
#   activate_window  按标题关键字切窗口          sync（有副作用）
#   save_note        追加一条本地便签            sync（有副作用）
#   search_files     在项目里搜文件名/正文        async_query（只读，耗时不阻塞对话）

import ctypes
import datetime
import json
import os
import webbrowser
from pathlib import Path
from urllib.parse import urlparse


SKIP_DIRS = {
    ".git", ".temp", ".vendor", "logs", "node_modules", "__pycache__",
    "runtime", "dist", "build", ".vs", ".idea", "sessions", "frames",
}
TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".json", ".md", ".yml", ".yaml",
    ".txt", ".toml", ".ini", ".cfg", ".bat", ".ps1", ".html", ".css", ".c", ".h",
    ".cpp", ".java", ".go", ".rs", ".lua", ".sql", ".sh", ".env", ".gitignore",
}
MAX_FILE_BYTES = 2 * 1024 * 1024


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


class ToolBox:
    """工具定义与执行"""

    def __init__(self, cfg, console):
        self.cfg = cfg
        self.console = console
        self.enabled = [str(x) for x in (cfg.tools.get("enabled") or [])]
        self.notes_path = cfg.local_path(cfg.tools.get("notes_file") or "notes/notes.md")
        self.search_max_results = int(cfg.tools.get("search_max_results") or 20)

    # ---------- 定义 ----------

    def definitions(self) -> list:
        specs = self._specs()
        return [spec for spec in specs if spec["name"] in self.enabled]

    @staticmethod
    def _specs() -> list:
        return [
            {
                "type": "function",
                "name": "get_time",
                "description": "查询当前时间。主人问现在几点、今天几号、星期几，或需要按时间安排事情时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "time_zone": {
                            "type": "string",
                            "description": "IANA 时区名，如 Asia/Shanghai；省略则用会话时区",
                        }
                    },
                    "required": [],
                },
                "read_only": True,
            },
            {
                "type": "function",
                "name": "open_url",
                "description": "用默认浏览器打开一个网页。主人让你打开某个网站、搜索页、文档链接时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "完整网址，必须是 http 或 https"}
                    },
                    "required": ["url"],
                },
            },
            {
                "type": "function",
                "name": "list_windows",
                "description": "列出当前打开的可见窗口标题。主人问“我开了哪些窗口”“现在有什么程序”，或需要先找窗口再切换时调用。",
                "parameters": {"type": "object", "properties": {}, "required": []},
                "read_only": True,
            },
            {
                "type": "function",
                "name": "activate_window",
                "description": "把标题包含指定关键字的窗口切到前台。主人说“切到浏览器/游戏/那个窗口”时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "窗口标题里的关键字，不区分大小写"}
                    },
                    "required": ["title"],
                },
            },
            {
                "type": "function",
                "name": "save_note",
                "description": "把一句话记进本地便签文件。主人让你记一下、待会提醒、存个笔记时调用。只记内容，不做定时提醒。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "要记录的内容，一句话"}
                    },
                    "required": ["content"],
                },
            },
            {
                "type": "function",
                "name": "search_files",
                "description": "在当前项目目录里按关键字搜索文件名和文本内容。主人问“项目里哪里写了 xxx”“找一下这个配置/函数”时调用。耗时较长，不会阻塞对话。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键字，支持英文或中文"},
                        "path": {"type": "string", "description": "相对项目根的目录，省略为项目根"},
                        "max_results": {"type": "integer", "description": "最多返回多少条，默认 20"},
                    },
                    "required": ["query"],
                },
                "execution_mode": "async_query",
                "read_only": True,
            },
        ]

    # ---------- 执行 ----------

    def execute(self, name: str, args: dict) -> str:
        args = args if isinstance(args, dict) else {}
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return _json({"ok": False, "error": f"未知工具: {name}"})
        try:
            return handler(args)
        except Exception as e:
            self.console.warn(f"工具 {name} 执行失败: {e}")
            return _json({"ok": False, "error": f"{type(e).__name__}: {e}"})

    # ---------- 各工具 ----------

    def _tool_get_time(self, args: dict) -> str:
        tz_name = str(args.get("time_zone") or self.cfg.session.get("time_zone") or "").strip()
        now = None
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                now = datetime.datetime.now(ZoneInfo(tz_name))
            except Exception:
                now = None
        if now is None:
            now = datetime.datetime.now().astimezone()
            tz_name = now.tzname() or "本地时间"
        weekday = "星期" + "一二三四五六日"[now.weekday()]
        return _json({
            "ok": True,
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": weekday,
            "time_zone": tz_name,
            "utc_offset": now.strftime("%z"),
        })

    def _tool_open_url(self, args: dict) -> str:
        url = str(args.get("url") or "").strip()
        if not url:
            return _json({"ok": False, "error": "url 不能为空"})
        if not url.lower().startswith(("http://", "https://")):
            return _json({"ok": False, "error": "只支持 http/https 网址"})
        parsed = urlparse(url)
        if not parsed.netloc:
            return _json({"ok": False, "error": f"网址不完整: {url}"})
        opened = webbrowser.open(url, new=2)
        if not opened:
            return _json({"ok": False, "error": "系统没有响应打开浏览器的请求"})
        return _json({"ok": True, "opened": url})

    def _tool_list_windows(self, args: dict) -> str:
        items, err = _enum_windows()
        if err:
            return _json({"ok": False, "error": err})
        if not items:
            return _json({"ok": True, "count": 0, "windows": []})
        return _json({"ok": True, "count": len(items), "windows": items[:50]})

    def _tool_activate_window(self, args: dict) -> str:
        keyword = str(args.get("title") or "").strip()
        if not keyword:
            return _json({"ok": False, "error": "title 不能为空"})
        items, err = _enum_windows()
        if err:
            return _json({"ok": False, "error": err})
        lowered = keyword.lower()
        match = next((w for w in items if lowered in w["title"].lower()), None)
        if not match:
            return _json({"ok": False, "error": f"没找到标题包含“{keyword}”的窗口"})
        ok, err = _activate_window(match["hwnd"])
        if not ok:
            return _json({"ok": False, "error": err, "window": match["title"]})
        return _json({"ok": True, "activated": match["title"]})

    def _tool_save_note(self, args: dict) -> str:
        content = str(args.get("content") or "").strip()
        if not content:
            return _json({"ok": False, "error": "content 不能为空"})
        try:
            self.notes_path.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(self.notes_path, "a", encoding="utf-8") as f:
                f.write(f"- [{stamp}] {content}\n")
        except Exception as e:
            return _json({"ok": False, "error": f"写入便签失败: {e}"})
        return _json({"ok": True, "file": str(self.notes_path), "content": content})

    def _tool_search_files(self, args: dict) -> str:
        query = str(args.get("query") or "").strip()
        if not query:
            return _json({"ok": False, "error": "query 不能为空"})
        raw_root = str(args.get("path") or self.cfg.tools.get("search_root") or "").strip()
        root = self.cfg.project_path(raw_root) if raw_root else self.cfg.project_root
        try:
            root = root.resolve()
            root.relative_to(self.cfg.project_root.resolve())
        except Exception:
            return _json({"ok": False, "error": f"搜索目录必须在项目内: {root}"})
        if not root.exists():
            return _json({"ok": False, "error": f"目录不存在: {root}"})
        limit = int(args.get("max_results") or self.search_max_results)
        limit = max(1, min(limit, 50))
        lowered = query.lower()

        results = []
        scanned = 0
        truncated = False
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            for filename in sorted(filenames):
                if len(results) >= limit:
                    truncated = True
                    break
                path = Path(dirpath) / filename
                try:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                name_hit = lowered in filename.lower()
                ext = path.suffix.lower()
                content_hit = None
                if ext in TEXT_EXTS or filename in ("AGENTS.md", "README", "config.json"):
                    scanned += 1
                    try:
                        text = path.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        text = ""
                    if lowered in text.lower():
                        content_hit = text
                if not name_hit and content_hit is None:
                    continue
                rel = str(path.relative_to(root)).replace("\\", "/")
                matches = []
                if content_hit is not None:
                    for lineno, line in enumerate(content_hit.splitlines(), 1):
                        if lowered in line.lower():
                            matches.append({"line": lineno, "text": line.strip()[:160]})
                            if len(matches) >= 3:
                                break
                results.append({"path": rel, "name_hit": name_hit, "matches": matches})
            if len(results) >= limit:
                truncated = True
                break

        return _json({
            "ok": True,
            "query": query,
            "root": str(root),
            "scanned_files": scanned,
            "results": results,
            "truncated": truncated,
        })


# ---------- Windows 窗口工具 ----------

def _enum_windows():
    """返回 ([{hwnd,title}], error)"""
    if os.name != "nt":
        return [], "当前系统不是 Windows，窗口工具不可用"
    try:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        items = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = (buf.value or "").strip()
                    if title:
                        items.append({"hwnd": int(hwnd), "title": title})
            return True

        user32.EnumWindows(_callback, 0)
        return items, ""
    except Exception as e:
        return [], f"枚举窗口失败: {e}"


def _activate_window(hwnd: int):
    if os.name != "nt":
        return False, "当前系统不是 Windows"
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        ok = user32.SetForegroundWindow(hwnd)
        if not ok:
            return False, "系统拒绝切换前台窗口（可能被其他窗口锁定）"
        return True, ""
    except Exception as e:
        return False, f"切换窗口失败: {e}"
