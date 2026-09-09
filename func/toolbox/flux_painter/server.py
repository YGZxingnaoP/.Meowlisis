# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/server.py
import asyncio
import json
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import websockets

from func.log.default_log import DefaultLog


class TBFluxPainterServer:
    """画板服务：HTTP(8090) 托管 painting_board.html + 图片/审查接口，WS(8767) 按 channel 推送"""

    def __init__(self, config, html_path=None):
        self.log = DefaultLog().getLogger()
        self.config = config
        self.http_port = config.http_port
        self.ws_port = config.ws_port
        self.html_path = html_path or os.path.join(os.path.dirname(__file__), "painting_board.html")
        self._clients = {}
        self._loop = None
        self._http_thread = None

    # ==================== WebSocket ====================
    @staticmethod
    def _channel_of(websocket) -> str:
        channel = "live"
        try:
            req = getattr(websocket, "request", None)
            if req is not None:
                qs = getattr(req, "query_string", None)
                q = parse_qs(qs.decode("utf-8", "ignore")) if isinstance(qs, bytes) else parse_qs(qs or "")
                channel = (q.get("channel") or ["live"])[0]
        except Exception:
            channel = "live"
        return str(channel or "live")

    async def _websocket_handler(self, websocket):
        channel = self._channel_of(websocket)
        self._clients.setdefault(channel, set()).add(websocket)
        try:
            await websocket.send(json.dumps({
                "type": "hello",
                "canvas_sizes": self.config.canvas_sizes,
                "review": bool(self.config.review_enabled),
                "artist_sources": self.config.artist_sources,
                "painting_board": f"http://127.0.0.1:{self.http_port}/painting_board.html",
            }, ensure_ascii=False))
            await websocket.wait_closed()
        finally:
            for ch, clients in list(self._clients.items()):
                clients.discard(websocket)
                if not clients:
                    self._clients.pop(ch, None)

    async def _run_websocket_server(self):
        self._ws_server = await websockets.serve(self._websocket_handler, "127.0.0.1", self.ws_port)
        self.log.info(f"[flux_painter] 画板 WebSocket 已启动，端口 {self.ws_port}")
        await self._ws_server.wait_closed()

    def _run_event_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._run_websocket_server())

    # ==================== HTTP ====================
    def _make_handler(self, base_dir):
        allow = [os.path.realpath(p) for p in
                 (self.config.backup_dir, self.config.comfy_output_dir)
                 if p]

        class _Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=base_dir, **kwargs)

            def log_message(self, *a):
                pass

            def _send_file(self, path, ctype):
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                except Exception:
                    self.send_error(404)

            def do_GET(self):
                parsed = urlparse(self.path)
                q = parse_qs(parsed.query)
                if parsed.path == "/paint_img":
                    path = (q.get("path") or [""])[0]
                    rp = os.path.realpath(path) if path else ""
                    if any(rp.startswith(a) for a in allow) and os.path.isfile(rp):
                        self._send_file(rp, "image/png")
                    else:
                        self.send_error(403)
                    return
                if parsed.path == "/api/review":
                    channel = (q.get("channel") or ["live"])[0]
                    passed = (q.get("pass") or ["0"])[0] in ("1", "true")
                    try:
                        from func.toolbox.flux_painter.painting_core import TBFluxPainterCore
                        TBFluxPainterCore().review_submit(channel, passed)
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b"ok")
                    except Exception:
                        self.send_error(500)
                    return
                return super().do_GET()

        return _Handler

    def _start_http_server(self):
        base_dir = os.path.dirname(self.html_path)
        try:
            httpd = HTTPServer(("127.0.0.1", self.http_port), self._make_handler(base_dir))
            self._http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            self._http_thread.start()
            self.log.info(f"[flux_painter] 画板页面: http://127.0.0.1:{self.http_port}/painting_board.html")
        except Exception:
            self.log.exception(f"[flux_painter] 画板 HTTP 服务启动失败(端口 {self.http_port})")

    # ==================== 生命周期 ====================
    def start(self):
        """幂等启动画板 HTTP + WS"""
        if self._loop is not None and self._http_thread is not None and self._http_thread.is_alive():
            self.log.info("[flux_painter] 画板服务已在运行，跳过重复启动")
            return
        self._start_http_server()
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_event_loop, daemon=True).start()
        self.log.info(f"✅ Flux 绘画画板服务已启动 | HTTP: {self.http_port} | WebSocket: {self.ws_port}")

    def broadcast(self, channel, payload):
        """向指定 channel 前端推送（channel 缺省 live）"""
        channel = str(channel or "live")
        clients = (self._clients or {}).get(channel)
        if not clients or self._loop is None:
            return
        try:
            message = json.dumps(payload, ensure_ascii=False)

            async def _send_all():
                for client in list(clients):
                    try:
                        await client.send(message)
                    except Exception:
                        clients.discard(client)

            asyncio.run_coroutine_threadsafe(_send_all(), self._loop)
        except Exception:
            self.log.exception("[flux_painter] 画板广播失败")


_flux_painter_server = None


def get_flux_painter_server():
    """全局画板服务单例（api.py 启用时 start）"""
    global _flux_painter_server
    if _flux_painter_server is None:
        from func.toolbox.flux_painter.config import TBFluxPainterConfig
        _flux_painter_server = TBFluxPainterServer(TBFluxPainterConfig())
    return _flux_painter_server
