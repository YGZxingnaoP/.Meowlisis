# -*- coding: utf-8 -*-
# func/subtitle/subtitle_server.py
# 浏览器字幕服务：HTTP 提供字幕页 + WebSocket 推送字幕文本
import asyncio
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os

import websockets


class SubtitleServer:
    def __init__(self, http_port=8080, ws_port=8765, html_path=None):
        self.http_port = http_port
        self.ws_port = ws_port
        self.html_path = html_path or os.path.join(os.path.dirname(__file__), "subtitle_template.html")
        self.websocket_clients = set()
        self._loop = None
        self._ws_server = None
        self._http_thread = None

    async def _websocket_handler(self, websocket):
        """处理 WebSocket 连接"""
        self.websocket_clients.add(websocket)
        try:
            # 保持连接，直到客户端断开
            await websocket.wait_closed()
        finally:
            self.websocket_clients.remove(websocket)

    async def _run_websocket_server(self):
        """启动 WebSocket 服务器"""
        self._ws_server = await websockets.serve(
            self._websocket_handler,
            "127.0.0.1",
            self.ws_port
        )
        print(f"WebSocket 服务器已启动，监听端口 {self.ws_port}")
        await self._ws_server.wait_closed()

    def _start_http_server(self):
        """在独立线程中启动 HTTP 服务器"""
        directory = os.path.dirname(self.html_path)
        handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(*args, directory=directory, **kwargs)
        httpd = HTTPServer(("127.0.0.1", self.http_port), handler)
        self._http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._http_thread.start()

    def start(self):
        """启动服务"""
        self._start_http_server()

        # 创建并启动新的事件循环来运行 WebSocket 服务器
        self._loop = asyncio.new_event_loop()
        thread = threading.Thread(target=self._run_event_loop, daemon=True)
        thread.start()

        print(f"✅ 字幕服务器已启动 | HTTP: {self.http_port} | WebSocket: {self.ws_port}")

    def _run_event_loop(self):
        """在新线程中运行事件循环"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._run_websocket_server())

    def send_subtitle(self, text: str):
        """向所有连接的客户端发送字幕"""
        if not self.websocket_clients or self._loop is None:
            return

        async def _send_all():
            """向所有客户端发送消息的协程"""
            if not self.websocket_clients:
                return

            # 复制客户端列表，避免在迭代时修改
            clients = list(self.websocket_clients)
            for client in clients:
                try:
                    await client.send(text)
                except Exception as e:
                    print(f"发送消息到客户端时出错: {e}")
                    # 如果出错，尝试从集合中移除
                    if client in self.websocket_clients:
                        self.websocket_clients.remove(client)

        # 安全地将协程提交到事件循环
        asyncio.run_coroutine_threadsafe(_send_all(), self._loop)


# 全局单例
_subtitle_server = None


def get_subtitle_server():
    global _subtitle_server
    if _subtitle_server is None:
        _subtitle_server = SubtitleServer()
        _subtitle_server.start()
    return _subtitle_server
