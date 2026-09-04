# -*- coding: utf-8 -*-
# func/sensevoice/port.py
# SenseVoice 服务端收发封装：WS 负责配置与结果，UDP 负责音频与实时控制

import json
import socket
import urllib.parse

import websockets


class SenseVoicePort:
    """封装与 SenseVoice 服务端的 WebSocket 连接与收发"""

    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.ws = None
        self._udp = None
        self._udp_addr = None

    async def connect(self):
        """建立 WebSocket 连接与 UDP 音频通道"""
        self.ws = await websockets.connect(
            self.config.server_url,
            subprotocols=["binary"],
            ping_interval=self.config.ping_interval,
            ping_timeout=self.config.ping_timeout
        )
        parsed = urllib.parse.urlparse(self.config.server_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 10095
        udp_port = self.config.udp_port
        if not udp_port:
            udp_port = port + 1
        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_addr = (host, int(udp_port))
        return self

    async def close(self):
        """关闭 WebSocket 连接与 UDP 通道"""
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
        if self._udp is not None:
            try:
                self._udp.close()
            except Exception:
                pass
            self._udp = None
            self._udp_addr = None

    async def send_ws_json(self, data: dict):
        """通过 WebSocket 发送 JSON 消息（启动配置）"""
        await self.ws.send(json.dumps(data, ensure_ascii=False))

    async def send_bytes(self, wav_name: str, data: bytes):
        """通过 UDP 发送一帧音频数据（PCM 16k 单声道）"""
        if self._udp is None or self._udp_addr is None:
            return
        try:
            self._udp.sendto(self._frame(1, wav_name, data), self._udp_addr)
        except OSError:
            pass

    async def send_ctrl(self, wav_name: str, data: dict):
        """通过 UDP 发送控制信号（说话状态切换）"""
        if self._udp is None or self._udp_addr is None:
            return
        try:
            payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self._udp.sendto(self._frame(2, wav_name, payload), self._udp_addr)
        except OSError:
            pass

    @staticmethod
    def _frame(ftype: int, wav_name: str, payload: bytes) -> bytes:
        """组装 UDP 帧：类型(1B) + 源名长度(1B) + 源名 + 载荷"""
        name = wav_name.encode('utf-8', 'ignore')
        if len(name) > 255:
            name = name[:255]
        return bytes([ftype, len(name)]) + name + payload

    def __aiter__(self):
        """支持 async for 迭代接收服务端消息"""
        return self.ws.__aiter__()

    async def __aenter__(self):
        """异步上下文进入：建立连接"""
        return await self.connect()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文退出：关闭连接"""
        await self.close()
