# -*- coding: utf-8 -*-
# func/subtitle/subtitle_server.py
# 浏览器字幕/收纳篮服务：HTTP 提供页面 + WebSocket 推送（tts/asr/basket 分角色订阅）
import asyncio
import threading
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os

import websockets

from func.rewards.fishcake_store import FishCakeStore


class SubtitleServer:
    def __init__(self, http_port=8080, ws_port=8765, html_path=None):
        self.http_port = http_port
        self.ws_port = ws_port
        self.html_path = html_path or os.path.join(os.path.dirname(__file__), "subtitle_template.html")
        # tts 前端（AI 说话/歌词字幕）、asr 前端（用户语音识别字幕）、basket（奖励收纳篮）
        self.websocket_clients = set()
        self.asr_clients = set()
        self.basket_clients = set()
        self._loop = None
        self._ws_server = None
        self._http_thread = None

    @staticmethod
    def _role_of(websocket) -> str:
        """按连接 query 参数订阅角色：?role=asr / ?role=basket / 缺省=tts"""
        role = 'tts'
        try:
            from urllib.parse import parse_qs
            req = getattr(websocket, 'request', None)
            if req is not None:
                qs = getattr(req, 'query_string', None)
                if qs:
                    role = parse_qs(qs.decode('utf-8', 'ignore')).get('role', ['tts'])[0]
                else:
                    path = getattr(req, 'path', '') or ''
                    if '?' in path:
                        role = parse_qs(path.split('?', 1)[1]).get('role', ['tts'])[0]
        except Exception:
            role = 'tts'
        return role if role in ('asr', 'basket') else 'tts'

    async def _websocket_handler(self, websocket):
        """按订阅角色加入对应客户端集合"""
        role = self._role_of(websocket)
        if role == 'asr':
            self.asr_clients.add(websocket)
        elif role == 'basket':
            self.basket_clients.add(websocket)
        else:
            self.websocket_clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.websocket_clients.discard(websocket)
            self.asr_clients.discard(websocket)
            self.basket_clients.discard(websocket)

    async def _run_websocket_server(self):
        self._ws_server = await websockets.serve(self._websocket_handler, "127.0.0.1", self.ws_port)
        print(f"WebSocket 服务器已启动，监听端口 {self.ws_port}")
        await self._ws_server.wait_closed()

    def _start_http_server(self):
        base_dir = os.path.dirname(self.html_path)

        def _make_handler(directory):
            class _Handler(SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=directory, **kwargs)

                def do_GET(self):
                    if self.path.split('?', 1)[0] == '/api/rewards':
                        try:
                            body = json.dumps(FishCakeStore().summary(history_limit=6),
                                              ensure_ascii=False).encode('utf-8')
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/json; charset=utf-8')
                            self.send_header('Content-Length', str(len(body)))
                            self.end_headers()
                            self.wfile.write(body)
                            return
                        except Exception:
                            self.send_response(500)
                            self.end_headers()
                            return
                    super().do_GET()

                def log_message(self, *args):
                    pass

            return _Handler

        httpd = HTTPServer(("127.0.0.1", self.http_port), _make_handler(base_dir))
        self._http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._http_thread.start()

    def start(self):
        self._start_http_server()
        self._loop = asyncio.new_event_loop()
        thread = threading.Thread(target=self._run_event_loop, daemon=True)
        thread.start()
        print(f"✅ 字幕服务器已启动 | HTTP: {self.http_port} | WebSocket: {self.ws_port}")

    def _run_event_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._run_websocket_server())

    def _broadcast(self, message: str, targets):
        if not targets or self._loop is None:
            return

        async def _send_all():
            for client in list(targets):
                try:
                    await client.send(message)
                except Exception:
                    self.websocket_clients.discard(client)
                    self.asr_clients.discard(client)
                    self.basket_clients.discard(client)

        asyncio.run_coroutine_threadsafe(_send_all(), self._loop)

    def send_subtitle(self, text: str, role: str = 'tts', name: str = None):
        """向对应角色前端推送（{"r": role, "t": text, "n": name}；clear 两者回待机）"""
        if (not self.websocket_clients and not self.asr_clients and not self.basket_clients) \
                or self._loop is None:
            return
        if role == 'clear':
            message = json.dumps({"r": "clear"}, ensure_ascii=False)
            self._broadcast(message, list(self.websocket_clients) + list(self.asr_clients))
            return
        payload = {"r": role or 'tts', "t": text}
        if name:
            payload["n"] = name
        message = json.dumps(payload, ensure_ascii=False)
        if role == 'asr':
            self._broadcast(message, list(self.asr_clients))
        elif role == 'basket':
            self._broadcast(message, list(self.basket_clients))
        else:
            self._broadcast(message, list(self.websocket_clients))

    def send_basket(self, payload: dict):
        """向收纳篮推送礼物入账事件（{"r":"basket", ...}）"""
        if not self.basket_clients or self._loop is None:
            return
        message = json.dumps({"r": "basket", **payload}, ensure_ascii=False)
        self._broadcast(message, list(self.basket_clients))


_subtitle_server = None


def get_subtitle_server():
    global _subtitle_server
    if _subtitle_server is None:
        _subtitle_server = SubtitleServer()
        _subtitle_server.start()
    return _subtitle_server
