# -*- coding: utf-8 -*-
# func/sensevoice/port.py - 纯 WebSocket 传输通道（发送缓冲不丢帧）
import asyncio
import json
import time

import websockets

WATERMARK = 32
STALL_LIMIT = 30.0


class SenseVoicePort:
    """WebSocket 传输：独立发送协程 + 无界队列（正常仅几帧，卡死才清理）"""

    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.ws = None
        self._q = None
        self._sender = None
        self._stall_since = 0.0

    async def connect(self):
        self.ws = await websockets.connect(
            self.config.server_url,
            subprotocols=["binary"],
            ping_interval=self.config.ping_interval,
            ping_timeout=self.config.ping_timeout
        )
        self._q = asyncio.Queue()
        self._sender = asyncio.ensure_future(self._send_loop())
        return self

    async def close(self):
        if self._sender is not None:
            self._sender.cancel()
            try:
                await self._sender
            except Exception:
                pass
            self._sender = None
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
        self._stall_since = 0.0

    async def _send_loop(self):
        try:
            while True:
                kind, payload = await self._q.get()
                if kind == 'a':
                    await self.ws.send(payload)
                else:
                    await self.ws.send(json.dumps(payload, ensure_ascii=False))
                if self._q.qsize() <= WATERMARK:
                    self._stall_since = 0.0
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._fail(e)

    def _fail(self, exc):
        try:
            self.log.warning(f"发送通道异常: {exc}")
            if self.ws is not None:
                asyncio.ensure_future(self.ws.close())
        except Exception:
            pass

    def submit(self, kind, payload):
        if self.ws is None or self._q is None:
            return False
        if self._sender is not None and self._sender.done():
            return False
        self._q.put_nowait((kind, payload))
        if self._q.qsize() > WATERMARK and self._stall_since == 0.0:
            self._stall_since = time.monotonic()
        return True

    def submit_audio(self, data):
        return self.submit('a', data)

    def submit_ctrl(self, data: dict):
        return self.submit('c', data)

    def check_health(self):
        if self.ws is None:
            return False
        if self._sender is not None and self._sender.done():
            return False
        if self._stall_since and time.monotonic() - self._stall_since > STALL_LIMIT:
            return False
        return True

    async def send_config(self, cfg: dict):
        await self.ws.send(json.dumps(cfg, ensure_ascii=False))

    def __aiter__(self):
        return self.ws.__aiter__()

    async def __aenter__(self):
        return await self.connect()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
