import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from cw.protocol import CWErrorCode, CWProtocolError

CW_STATIC = {"index.html", "app.js", "viewer.js", "timeline.js", "style.css"}


class CWWeb:
    def __init__(self, config, session, operator, agent, store, relay, journal, device):
        self.config = config
        self.session = session
        self.operator = operator
        self.agent = agent
        self.store = store
        self.relay = relay
        self.journal = journal
        self.device = device
        self._server = None
        self._thread = None

    def start(self):
        handler = self._make_handler()
        try:
            self._server = ThreadingHTTPServer((self.config.host, self.config.port), handler)
        except OSError as exc:
            raise RuntimeError("Web 端口 %s 启动失败：%s" % (self.config.port, exc))
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="cw-web",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        try:
            if self._server is not None:
                self._server.shutdown()
        except Exception:
            pass

    def url(self):
        return "http://%s:%d" % (self.config.host, self.config.port)

    def _make_handler(self):
        web = self

        class CWHandler(BaseHTTPRequestHandler):
            server_version = "CatPaws/1.0"
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                web._route(self, "GET")

            def do_POST(self):
                web._route(self, "POST")

            def log_message(self, *args):
                pass

        return CWHandler

    def _send_json(self, handler, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            handler.send_response(status)
            handler.send_header("Content-Type", "application/json; charset=utf-8")
            handler.send_header("Content-Length", str(len(body)))
            handler.send_header("Cache-Control", "no-store")
            handler.end_headers()
            handler.wfile.write(body)
        except Exception:
            pass

    def _send_bytes(self, handler, body, content_type, status=200):
        try:
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(body)))
            handler.send_header("Cache-Control", "no-store")
            handler.end_headers()
            handler.wfile.write(body)
        except Exception:
            pass

    def _read_body(self, handler):
        try:
            length = int(handler.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = handler.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _static(self, handler, name):
        if name not in CW_STATIC:
            self._send_json(handler, {"ok": False, "code": "E_NOT_FOUND"}, 404)
            return
        path = os.path.join(self.config.web_dir, name)
        if not os.path.isfile(path):
            self._send_json(handler, {"ok": False, "code": "E_NOT_FOUND"}, 404)
            return
        with open(path, "rb") as handle:
            body = handle.read()
        content_type = "text/html; charset=utf-8"
        if name.endswith(".js"):
            content_type = "application/javascript; charset=utf-8"
        elif name.endswith(".css"):
            content_type = "text/css; charset=utf-8"
        self._send_bytes(handler, body, content_type)

    def _route(self, handler, method):
        parsed = urlparse(handler.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if method == "GET":
                if path in ("/", "/index.html"):
                    self._static(handler, "index.html")
                    return
                if path.startswith("/js/"):
                    self._static(handler, path.split("/")[-1])
                    return
                if path == "/cw/status":
                    self._send_json(handler, self._status())
                    return
                if path == "/cw/ops":
                    limit = int((query.get("limit") or ["200"])[0])
                    self._send_json(handler, {"ok": True, "items": self.journal.tail(limit)})
                    return
                if path == "/cw/actions":
                    self._send_json(handler, {"ok": True, "items": self.store.list()})
                    return
                if path == "/cw/screenshot":
                    png = self.device.screenshot(max_edge=self.config.screenshot_max_edge)
                    self._send_bytes(handler, png, "image/png")
                    return
                if path == "/cw/config":
                    self._send_json(handler, {"ok": True, "config": self.config.as_public()})
                    return
                self._send_json(handler, {"ok": False, "code": "E_NOT_FOUND"}, 404)
                return
            body = self._read_body(handler)
            if path == "/cw/start":
                goal = str(body.get("goal") or "").strip()
                if not goal:
                    self._send_json(handler, {"ok": False, "code": CWErrorCode.BAD_REQUEST,
                                              "message": "goal 不能为空"})
                    return
                if not self.agent.start(goal):
                    self._send_json(handler, {"ok": False, "code": CWErrorCode.BUSY,
                                              "message": "已有链路在跑"})
                    return
                self._send_json(handler, {"ok": True, "session": self.session.snapshot()})
                return
            if path == "/cw/stop":
                self.agent.stop(str(body.get("reason") or "web"))
                self._send_json(handler, {"ok": True, "session": self.session.snapshot()})
                return
            if path == "/cw/answer":
                text = str(body.get("text") or "")
                accepted = self.session.answer(text)
                if not accepted:
                    queued = self.session.push_instruction(text)
                    self._send_json(handler, {"ok": bool(queued),
                                              "queued": bool(queued),
                                              "code": CWErrorCode.OK if queued
                                              else CWErrorCode.UNAVAILABLE})
                    return
                self._send_json(handler, {"ok": accepted, "queued": False,
                                          "code": CWErrorCode.OK if accepted
                                          else CWErrorCode.BAD_REQUEST})
                return
            if path == "/cw/stream":
                on = bool(body.get("on", True))
                sent = self.relay.start_stream() if on else self.relay.stop_stream()
                self._send_json(handler, {"ok": True, "sent": bool(sent),
                                          "relay": self.relay.status()})
                return
            if path == "/cw/actions/verify":
                manifest = self.store.set_verified(str(body.get("id") or ""),
                                                   bool(body.get("verified", True)))
                self._send_json(handler, {"ok": True, "manifest": manifest})
                return
            if path == "/cw/actions/updatable":
                manifest = self.store.set_updatable(str(body.get("id") or ""),
                                                    bool(body.get("updatable", True)))
                self._send_json(handler, {"ok": True, "manifest": manifest})
                return
            self._send_json(handler, {"ok": False, "code": "E_NOT_FOUND"}, 404)
        except CWProtocolError as exc:
            self._send_json(handler, {"ok": False, "code": exc.code, "message": exc.message})
        except Exception as exc:
            self._send_json(handler, {"ok": False, "code": CWErrorCode.INTERNAL,
                                      "message": "%s: %s" % (type(exc).__name__, exc)})

    def _status(self):
        device = {"mock": bool(getattr(self.device, "is_mock", False))}
        info = {}
        try:
            info = self.device.device_info()
        except Exception as exc:
            device["error"] = str(exc)
        return {
            "ok": True,
            "session": self.session.snapshot(),
            "agent_busy": self.agent.busy(),
            "pending_question": self.session.pending_question(),
            "relay": self.relay.status(),
            "device": {"mock": device["mock"], "info": info, "error": device.get("error", "")},
            "config": self.config.as_public(),
            "final": self.agent.last_final(),
            "final_ok": bool(self.agent.last_concluded()),
        }
