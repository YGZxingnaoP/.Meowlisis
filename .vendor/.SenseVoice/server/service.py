# -*- coding: utf-8 -*-
# server/service.py - WebSocket 服务装配：每连接消息队列 + 独立推理 worker

import asyncio
import json

import websockets

from speaker import SpeakerVerification
from session import SenseVoiceSession

connected = set()


async def _session_worker(session, q):
    """按序处理该连接消息：音频累积 / 控制与识别（识别不阻塞接收）"""
    while True:
        kind, payload = await q.get()
        try:
            if kind == 1:
                session.handle_audio(payload)
            else:
                await session.handle_text_message(json.loads(payload.decode("utf-8")))
        except Exception as e:
            print(f"会话处理异常: {e}")


async def handle_client(websocket, ctx):
    """收消息入队；每连接一个 worker 执行推理，接收永不回堵"""
    sv = SpeakerVerification(ctx.sv_model, ctx.args.speaker_db_path,
                             ctx.args.speaker_db_reload_sec, ctx.args.sv_threshold)
    session = SenseVoiceSession(websocket, sv, ctx)
    q = asyncio.Queue()
    worker = asyncio.ensure_future(_session_worker(session, q))
    connected.add(websocket)
    print(f"新客户端连接，当前连接数: {len(connected)}")
    try:
        async for message in websocket:
            if isinstance(message, str):
                q.put_nowait((2, message.encode("utf-8")))
            else:
                q.put_nowait((1, message))
    except websockets.exceptions.ConnectionClosed:
        print("客户端连接关闭")
    except Exception as e:
        print(f"连接异常: {e}")
    finally:
        worker.cancel()
        try:
            await worker
        except (Exception, asyncio.CancelledError):
            pass
        connected.discard(websocket)
        print(f"客户端断开，当前连接数: {len(connected)}")


async def serve(ctx):
    """启动 WebSocket 识别服务并常驻"""
    async def _handler(websocket, path=None):
        await handle_client(websocket, ctx)

    server = await websockets.serve(
        _handler,
        ctx.args.host,
        ctx.args.port,
        subprotocols=["binary"],
        ping_interval=60,
        ping_timeout=30,
    )
    print(f"SenseVoice WebSocket 服务已启动: ws://{ctx.args.host}:{ctx.args.port}")
    await server.wait_closed()
