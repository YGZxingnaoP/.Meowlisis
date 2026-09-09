# -*- coding: utf-8 -*-
# func/toolbox/svg_painter/server.py
# SVG 绘画画板服务：HTTP 提供页面(8090) + WebSocket 实时推送(8767)
# - 按 channel 分组（live / qq_private / qq_group），每个绘画会话独立画布
# - 页面用 ?channel=xxx 指定查看哪个会话的画布（默认 live）
import asyncio
import json
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs

import websockets

from func.log.default_log import DefaultLog


class TBSvgPainterServer:
    """绘画画板服务：静态托管 svg_board.html + 按 channel 的 WS 广播"""

    def __init__(self, http_port=8090, ws_port=8767, html_path=None):
        self.log = DefaultLog().getLogger()
        self.http_port = http_port
        self.ws_port = ws_port
        self.html_path = html_path or os.path.join(os.path.dirname(__file__), "svg_board.html")
        self._clients = {}          # channel -> set(websocket)
        self._loop = None
        self._ws_server = None
        self._http_thread = None

    # ==================== WebSocket ====================
    @staticmethod
    def _channel_of(websocket) -> str:
        channel = "live"
        try:
            req = getattr(websocket, "request", None)
            if req is not None:
                qs = getattr(req, "query_string", None)
                if qs:
                    q = parse_qs(qs.decode("utf-8", "ignore")) if isinstance(qs, bytes) else parse_qs(qs or "")
                    channel = (q.get("channel") or ["live"])[0]
                else:
                    path = getattr(req, "path", "") or ""
                    if "?" in path:
                        q = parse_qs(path.split("?", 1)[1])
                        channel = (q.get("channel") or ["live"])[0]
        except Exception:
            channel = "live"
        return str(channel or "live")

    async def _websocket_handler(self, websocket):
        channel = self._channel_of(websocket)
        self._clients.setdefault(channel, set()).add(websocket)
        try:
            # 首帧：推该会话画布快照
            try:
                from func.toolbox.svg_painter.core import TBSvgPainterCore
                core = TBSvgPainterCore()
                board = core.board_for(channel)
                if board is not None and board.to_svg():
                    await websocket.send(json.dumps(
                        {"type": "snapshot", "svg": board.to_svg()}, ensure_ascii=False))
                else:
                    await websocket.send(json.dumps({
                        "type": "clear",
                        "width": getattr(board, "width", 600) if board else 600,
                        "height": getattr(board, "height", 800) if board else 800,
                        "bg": getattr(board, "bg", "none") if board else "none",
                    }, ensure_ascii=False))
            except Exception:
                pass
            await websocket.wait_closed()
        finally:
            for ch, clients in list(self._clients.items()):
                clients.discard(websocket)
                if not clients:
                    self._clients.pop(ch, None)

    async def _run_websocket_server(self):
        self._ws_server = await websockets.serve(self._websocket_handler, "127.0.0.1", self.ws_port)
        self.log.info(f"[svg_painter] 画板 WebSocket 已启动，端口 {self.ws_port}")
        await self._ws_server.wait_closed()

    def _run_event_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._run_websocket_server())

    # ==================== HTTP ====================
    def _start_http_server(self):
        base_dir = os.path.dirname(self.html_path)

        def _make_handler(directory):
            class _Handler(SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=directory, **kwargs)

                def log_message(self, *args):
                    pass

            return _Handler

        try:
            httpd = HTTPServer(("127.0.0.1", self.http_port), _make_handler(base_dir))
            self._http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            self._http_thread.start()
            self.log.info(f"[svg_painter] 画板页面: http://127.0.0.1:{self.http_port}/svg_board.html")
        except Exception:
            self.log.exception(f"[svg_painter] 画板 HTTP 服务启动失败(端口 {self.http_port})")

    # ==================== 生命周期 ====================
    def start(self):
        if self._loop is not None and self._http_thread is not None and self._http_thread.is_alive():
            self.log.info("[svg_painter] 画板服务已在运行，跳过重复启动")
            return
        self._start_http_server()
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        thread = threading.Thread(target=self._run_event_loop, daemon=True)
        thread.start()
        self.log.info(f"✅ SVG 绘画画板服务已启动 | HTTP: {self.http_port} | WebSocket: {self.ws_port}")

    def broadcast(self, channel: str, payload: dict):
        """向指定会话画布的前端推送消息（channel 缺省 live）"""
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
            self.log.exception("[svg_painter] 画板广播失败")


_svg_painter_server = None


def get_svg_painter_server():
    """全局画板服务单例（由 api.py 在启用时 start）"""
    global _svg_painter_server
    if _svg_painter_server is None:
        from func.toolbox.svg_painter.config import TBSvgPainterConfig
        cfg = TBSvgPainterConfig()
        _svg_painter_server = TBSvgPainterServer(cfg.http_port, cfg.ws_port)
    return _svg_painter_server
