# -*- coding: utf-8 -*-
# func/sensevoice/port.py
# SenseVoice 服务端 WebSocket 收发封装

import json
import websockets


class SenseVoicePort:
    """封装与 SenseVoice 服务端的 WebSocket 连接与收发"""

    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.ws = None

    async def connect(self):
        """建立 WebSocket 连接"""
        self.ws = await websockets.connect(
            self.config.server_url,
            subprotocols=["binary"],
            ping_interval=self.config.ping_interval,
            ping_timeout=self.config.ping_timeout
        )
        return self

    async def close(self):
        """关闭 WebSocket 连接"""
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

    async def send_bytes(self, data: bytes):
        """发送二进制音频帧"""
        await self.ws.send(data)

    async def send_json(self, data: dict):
        """发送 JSON 文本消息"""
        await self.ws.send(json.dumps(data, ensure_ascii=False))

    def __aiter__(self):
        """支持 async for 迭代接收服务端消息"""
        return self.ws.__aiter__()

    async def __aenter__(self):
        """异步上下文进入：建立连接"""
        return await self.connect()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文退出：关闭连接"""
        await self.close()
