# -*- coding: utf-8 -*-
# func/toolbox/napcat/napcat_core/connection.py
# NapCat WebSocket 连接层：连接、重连、收事件、echo 队列、事件分发

import asyncio
import json
import threading
from typing import Optional, Callable

import websockets


class TBNapCatConnection:
    """NapCat WS 连接层：负责连接、重连、收事件、API 响应分发。

    不直接处理业务逻辑；事件通过回调（on_private_message / on_group_message / on_poke）
    转发给事件处理层。停止时调用 on_stop_cleanup 清理外部状态（如缓冲定时器）。
    """

    def __init__(self, log, config):
        self.log = log
        self.config = config
        self.enabled = config.enabled

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.ws = None
        self._echo_seq = 0
        self._pending_echo = {}
        # 事件循环就绪信号（用于消除 loop 建立前的竞态）
        self._loop_ready = threading.Event()

        # 事件回调（由门面 TBNapCatCore 注入到事件处理层）
        self.on_private_message: Optional[Callable[[dict], None]] = None
        self.on_group_message: Optional[Callable[[dict], None]] = None
        self.on_poke: Optional[Callable[[dict], None]] = None
        # 停止时的清理回调（由门面注入，用于清空缓冲定时器）
        self.on_stop_cleanup: Optional[Callable[[], None]] = None
        # 事件落盘回调（debug_event_dump 时由门面注入）
        self.dump_event: Optional[Callable[[dict], None]] = None

    # ==================== 生命周期 ====================
    def start(self):
        """启动后台线程（未启用则直接返回）"""
        if not self.enabled:
            self.log.info("NapCat 未启用")
            return
        if self.thread and self.thread.is_alive():
            self.log.warning("NapCat 已在运行")
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
        self.log.info(f"NapCat 客户端已启动，目标: {self.config.ws_url}")

    def stop(self):
        """停止后台线程"""
        self.running = False
        # 清理所有待发送的消息缓冲定时器（由门面注入的回调执行）
        if self.on_stop_cleanup:
            self.on_stop_cleanup()
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout=5)
        self.log.info("NapCat 客户端已停止")

    def _run_async_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        # 标记事件循环已就绪，唤醒等待中的发送线程
        self._loop_ready.set()
        try:
            self.loop.run_until_complete(self._main())
        except Exception as e:
            self.log.error(f"NapCat 主协程异常: {e}")
        finally:
            self._loop_ready.clear()
            self.loop.close()

    async def _main(self):
        while self.running:
            try:
                await self._connect()
                self.log.info(f"已连接 NapCat: {self.config.ws_url}")
                await self._recv_loop()
            except Exception as e:
                if self.running:
                    self.log.error(f"NapCat 连接异常: {e}，3秒后重连")
                    await asyncio.sleep(3)
                else:
                    break
            finally:
                await self._close()

    # ==================== 连接 ====================
    async def _connect(self):
        kwargs = {"subprotocols": ["binary"]}
        if self.config.access_token:
            kwargs["extra_headers"] = {"Authorization": f"Bearer {self.config.access_token}"}
        self.ws = await websockets.connect(self.config.ws_url, **kwargs)

    async def _close(self):
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

    async def _recv_loop(self):
        async for message in self.ws:
            if isinstance(message, bytes):
                continue
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue
            await self._handle(data)

    async def _handle(self, data: dict):
        """分发事件与 API 响应"""
        # 调试：原始事件落盘（用于拿群机器人消息样本，默认关闭）
        if self.config.debug_event_dump and data.get("post_type") and self.dump_event:
            self.dump_event(data)
        # API 响应（带 echo）：resolve 等待中的 future
        echo = data.get("echo")
        if echo is not None and echo in self._pending_echo:
            fut = self._pending_echo.pop(echo, None)
            if fut and not fut.done():
                fut.set_result(data)
            return
        post_type = data.get("post_type")
        if post_type == "message" and data.get("message_type") == "private":
            if self.on_private_message:
                # 新线程处理，避免阻塞事件循环
                threading.Thread(target=self.on_private_message, args=(data,), daemon=True).start()
        elif post_type == "message" and data.get("message_type") == "group":
            if self.on_group_message:
                threading.Thread(target=self.on_group_message, args=(data,), daemon=True).start()
        elif post_type == "notice":
            # 戳一戳等通知事件
            if data.get("sub_type") == "poke" and self.on_poke:
                threading.Thread(target=self.on_poke, args=(data,), daemon=True).start()

    # ==================== 发送基础设施（供 api_client 使用） ====================
    def _next_echo(self) -> str:
        self._echo_seq += 1
        return f"napcat_{self._echo_seq}"

    def _wait_loop_ready(self, timeout: float = 3.0) -> bool:
        """等待事件循环就绪（消除启动初期竞态），超时返回 False"""
        if not self.enabled:
            return False
        return self._loop_ready.wait(timeout)

    async def _call_action(self, echo: str, action: str, params: dict):
        """异步调用 API 并等待响应（内部使用）"""
        if self.ws is None:
            return None
        fut = self.loop.create_future()
        self._pending_echo[echo] = fut
        try:
            await self.ws.send(json.dumps({
                "action": action, "params": params, "echo": echo,
            }, ensure_ascii=False))
        except Exception:
            self._pending_echo.pop(echo, None)
            raise
        try:
            return await asyncio.wait_for(fut, timeout=5.0)
        except asyncio.TimeoutError:
            self._pending_echo.pop(echo, None)
            return None
