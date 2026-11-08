# -*- coding: utf-8 -*-
"""插件自带的只读 Web 面板（不依赖主 GUI，也不依赖 mod 的 dashboard）。

    http://127.0.0.1:8760/

只读接口：
    /api/state      当前状态 + 今日计划 + 长线 + 待办 + 最近日记/日志/记忆/习惯
    /api/day?date=  某一天的日志 / 日记 / 计划 / 待办
    /api/diary      日记列表
    /api/journal    日志
    /api/memory     记忆 tips
    /api/habits     习惯
    /api/plans      长线 + 当日计划
    /api/todos      待办
    /api/agent      角色状态（当前动作 / 心情 / 计划摘要）
POST /api/request {"text": "..."} 让角色判断一条建议（面板上也可以提建议）
POST /api/play   {"action": "start|stop|pause|resume|grant|sleep"}
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .records import diary, habits, journal, memtips, plans, store as store_mod, todos


class _Handler(BaseHTTPRequestHandler):
    server_version = "StardewAgentPanel/1.1"

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/":
            return self._file("index.html", "text/html; charset=utf-8")
        if path in ("/app.js", "/style.css", "/favicon.svg"):
            ctype = {"app.js": "application/javascript; charset=utf-8",
                     "style.css": "text/css; charset=utf-8",
                     "favicon.svg": "image/svg+xml"}[path[1:]]
            return self._file(path[1:], ctype)
        if path.startswith("/api/"):
            return self._api(path, parse_qs(parsed.query))
        return self._json({"ok": False, "reason": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8", "replace") or "{}")
        except Exception:
            payload = {}
        path = parsed.path.rstrip("/")
        if path == "/api/request":
            return self._request(payload)
        if path == "/api/todo":
            return self._todo(payload)
        if path == "/api/play":
            return self._play(payload)
        return self._json({"ok": False, "reason": "not found"}, 404)

    # ---- 静态文件 ----
    def _file(self, name, ctype):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
        path = os.path.join(base, name)
        if not os.path.isfile(path):
            return self._json({"ok": False, "reason": "missing asset: " + name}, 404)
        with open(path, "rb") as handle:
            data = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ---- JSON ----
    def _json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _agent(self):
        plugin = getattr(self.server, "plugin", None)
        return getattr(plugin, "_agent", None) if plugin is not None else None

    def _store(self, save=""):
        plugin = getattr(self.server, "plugin", None)
        agent = getattr(plugin, "_agent", None) if plugin is not None else None
        current = getattr(agent, "store", None) if agent is not None else None
        if not save:
            return current
        if current is not None and os.path.basename(current.root) == save:
            return current
        if plugin is None or getattr(plugin, "ctx", None) is None:
            return None
        return store_mod.Store(plugin.ctx, save)

    def _api(self, path, query):
        try:
            save = (query.get("save") or [""])[0]
            date = (query.get("date") or [""])[0]
            if path == "/api/saves":
                plugin = getattr(self.server, "plugin", None)
                ctx = getattr(plugin, "ctx", None)
                return self._json({"ok": True, "items": store_mod.list_saves(ctx) if ctx else []})
            if path == "/api/state":
                return self._json(self._state(save, date))
            if path == "/api/day":
                return self._json(self._day(date, save))
            if path == "/api/diary":
                try:
                    limit = max(1, min(1000, int((query.get("limit") or ["30"])[0])))
                except (TypeError, ValueError):
                    limit = 30
                return self._json(self._diary(limit=limit, save=save))
            if path == "/api/journal":
                return self._json(self._journal(date, save))
            if path == "/api/memory":
                return self._json(self._memory(save))
            if path == "/api/digest":
                return self._json(self._digest(save, date))
            if path == "/api/habits":
                return self._json(self._habits(save))
            if path == "/api/plans":
                return self._json(self._plans(save, date))
            if path == "/api/todos":
                return self._json(self._todos(date, save))
            if path == "/api/agent":
                return self._json(self._agent_status())
            return self._json({"ok": False, "reason": "unknown api"}, 404)
        except Exception as exc:
            return self._json({"ok": False, "reason": str(exc)}, 500)

    def _request(self, payload):
        agent = self._agent()
        text = str((payload or {}).get("text") or "").strip()
        if not text or agent is None:
            return self._json({"ok": False, "reason": "empty request"}, 400)
        result = agent.handle_request(text, by="面板", source="dashboard")
        return self._json({"ok": True, "result": result})

    def _todo(self, payload):
        agent = self._agent()
        item_id = str((payload or {}).get("id") or "").strip()
        action = str((payload or {}).get("action") or "done").strip().lower()
        if agent is None or agent.store is None or not item_id:
            return self._json({"ok": False, "reason": "todo not ready"}, 400)
        if action != "done":
            return self._json({"ok": False, "reason": "unsupported action"}, 400)
        done = todos.complete_like(agent.store, agent.day_stamp, item_id)
        return self._json({"ok": True, "done": done})

    def _play(self, payload):
        plugin = getattr(self.server, "plugin", None)
        agent = self._agent()
        if plugin is None or agent is None:
            return self._json({"ok": False, "reason": "agent not ready"}, 400)
        action = str((payload or {}).get("action") or "status").strip().lower()
        try:
            if action == "start":
                text = plugin.play_action("start")
                return self._json({"ok": True, "message": text or "开始玩了",
                                   "playing": bool(agent.playing)})
            if action == "stop":
                plugin.play_action("stop")
                return self._json({"ok": True, "message": "停下了", "playing": False})
            if action == "pause":
                agent.pause()
                return self._json({"ok": True, "message": "暂停"})
            if action == "resume":
                agent.resume()
                return self._json({"ok": True, "message": "继续"})
            if action == "sleep":
                ok, message = agent.request_sleep()
                return self._json({"ok": True, "message": message})
            if action == "grant":
                goal = str((payload or {}).get("goal") or "").strip()
                result = agent.handle_request(goal, by="面板", source="grant")
                return self._json({"ok": result.get("mode") != "refuse",
                                   "message": result.get("reply") or ""})
            return self._json({"ok": True, "status": agent.status_text()})
        except Exception as exc:
            return self._json({"ok": False, "reason": str(exc)}, 500)

    # ---- 数据组装 ----
    def _state(self, save="", date=""):
        agent = self._agent()
        store = self._store(save)
        if store is None:
            return {"ok": False, "connected": False, "reason": "agent not ready"}
        is_current = agent is not None and agent.store is not None and \
            os.path.basename(agent.store.root) == os.path.basename(store.root)
        if is_current:
            status = agent.status()
            status.pop("long_term", None)
            status.pop("todos", None)
            status.pop("diary_latest", None)
            day = date or agent.day_stamp
        else:
            day = date or store.latest_day("diary") or store.latest_day("plans/day") or ""
            status = {"connected": False, "playing": False, "world_key": save,
                      "activity": "历史存档", "current": {}}
        long_term = plans.load_long_term(store, getattr(agent, "long_term_config", ""), 3) \
            if is_current else plans.load_long_term(store, "", 3)
        return {
            "ok": True,
            "server_time": store_mod.now(),
            "save": os.path.basename(store.root),
            "current": is_current,
            "day": day,
            "agent": status,
            "plan": plans.load_day(store, day) if day else None,
            "long_term": long_term,
            "todos": todos.load_day(store, day) if day else None,
            "diary": self._diary(limit=14, save=save),
            "journal": self._journal(day, save=save),
            "memory": self._memory(save),
            "habits": self._habits(save),
            "digest": self._digest(save, day) if day else {"ok": True, "digest": None},
        }

    def _agent_status(self):
        agent = self._agent()
        if agent is None:
            return {"ok": False, "reason": "agent not ready"}
        return {"ok": True, "agent": agent.status(), "text": agent.status_text()}

    def _day(self, date, save=""):
        store = self._store(save)
        if store is None or not date:
            return {"ok": False, "reason": "no date"}
        return {
            "ok": True,
            "date": date,
            "diary": diary.read(store, date),
            "journal": journal.read_day(store, date),
            "plan": plans.load_day(store, date),
            "todos": todos.load_day(store, date),
        }

    def _diary(self, limit=30, save=""):
        store = self._store(save)
        if store is None:
            return {"ok": True, "items": []}
        items = []
        for date in diary.list_days(store, limit=limit):
            data = diary.read(store, date)
            if data:
                items.append(data)
        return {"ok": True, "items": items}

    def _journal(self, date, save=""):
        store = self._store(save)
        if store is None:
            return {"ok": True, "items": []}
        agent = self._agent()
        date = date or (agent.day_stamp if agent else "")
        rows = journal.read_day(store, date) if date else []
        return {"ok": True, "date": date, "items": rows}

    def _memory(self, save=""):
        store = self._store(save)
        if store is None:
            return {"ok": True, "total": 0, "items": []}
        items = memtips.all_tips(store)
        stats = memtips.stats(store)
        return {"ok": True, "total": len(items), "by_tag": stats.get("by_tag", {}),
                "items": list(reversed(items))[:200]}

    def _habits(self, save=""):
        store = self._store(save)
        if store is None:
            return {"ok": True, "items": [], "latest": None}
        keys = habits.list_windows(store)
        windows = [habits.load_window(store, key) for key in keys[-8:]]
        return {"ok": True, "latest": habits.latest(store), "windows": windows}

    def _digest(self, save="", date=""):
        store = self._store(save)
        if store is None:
            return {"ok": False, "reason": "no store", "digest": None}
        agent = self._agent()
        day = date or (agent.day_stamp if agent else "")
        if not day:
            return {"ok": True, "date": "", "digest": None}
        data = store.load_json(store.memory_digest_path(day), None)
        return {"ok": True, "date": day, "digest": data}

    def _plans(self, save="", date=""):
        store = self._store(save)
        agent = self._agent()
        if store is None:
            return {"ok": False, "reason": "no store"}
        day = date or (agent.day_stamp if agent else "")
        return {"ok": True,
                "long_term": plans.load_long_term(store, getattr(agent, "long_term_config", ""), 3),
                "day": plans.load_day(store, day) if day else None}

    def _todos(self, date, save=""):
        store = self._store(save)
        if store is None:
            return {"ok": False, "reason": "no store"}
        agent = self._agent()
        date = date or (agent.day_stamp if agent else "")
        return {"ok": True, "date": date, "data": todos.load_day(store, date)}


class DashboardServer:
    def __init__(self, plugin, port=8760):
        self.plugin = plugin
        self.port = int(port or 8760)
        self.httpd = None
        self.thread = None

    def start(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        self.httpd.plugin = self.plugin
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       name="stardew_dashboard", daemon=True)
        self.thread.start()

    def stop(self):
        if self.httpd is not None:
            try:
                self.httpd.shutdown()
            except Exception:
                pass
            try:
                self.httpd.server_close()
            except Exception:
                pass
        self.httpd = None
        self.thread = None
