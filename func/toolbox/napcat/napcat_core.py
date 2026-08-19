# -*- coding: utf-8 -*-
# func/toolbox/napcat/napcat_core.py
# NapCat 核心：作为客户端连接 NapCat OneBot v11 正向 WebSocket，收发数据与事件

import asyncio
import json
import threading
from typing import Optional, Callable

import websockets

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.napcat.config import TBNapCatConfig


@singleton
class TBNapCatCore:
    """NapCat 控制核心：正向 WS 客户端，负责连接、收事件、发 API 请求"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBNapCatConfig()
        self.enabled = self.config.enabled

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.ws = None
        self._echo_seq = 0
        self._pending_echo = {}
        # 事件循环就绪信号（用于消除 loop 建立前的竞态）
        self._loop_ready = threading.Event()

        # 私聊消息回调（默认指向内部串联处理：解析→拉历史→TBoxCore.receive_qq）
        self.on_private_message: Optional[Callable[[dict], None]] = self._handle_private_message
        # 消息解析与历史拉取
        from func.toolbox.napcat.message.get_message import TBGetMessage
        from func.toolbox.napcat.message.get_record import TBGetRecord
        self.get_message = TBGetMessage()
        self.get_record = TBGetRecord()

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

    # ==================== 私聊消息处理 ====================
    def _handle_private_message(self, event: dict):
        """串联私聊处理：解析 → 拉历史 → TBoxCore.receive_qq（通过 pipeline 传递）"""
        try:
            parsed = self.get_message.parse(event)
            if not parsed or not parsed.get("text"):
                return
            self_id = event.get("self_id")
            short_memory = self.get_record.fetch(parsed["user_id"], self_id)
            from func.toolbox.toolbox_core import TBoxCore
            TBoxCore().receive_qq(
                parsed["username"], parsed["user_id"], parsed["text"], short_memory
            )
        except Exception:
            self.log.exception("处理私聊消息异常")

    # ==================== 发送 API ====================
    def _next_echo(self) -> str:
        self._echo_seq += 1
        return f"napcat_{self._echo_seq}"

    def _wait_loop_ready(self, timeout: float = 3.0) -> bool:
        """等待事件循环就绪（消除启动初期竞态），超时返回 False"""
        if not self.enabled:
            return False
        return self._loop_ready.wait(timeout)

    def send_private_text(self, user_id, text: str):
        """发送私聊文本（线程安全，异步发送并记录结果）"""
        if not text or not self.enabled:
            return
        if not self._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过发送")
            return
        self.log.info(f"[NapCat] 发送文本 → {user_id}: {text[:40]}")
        self._submit_send("send_private_msg", {
            "user_id": int(user_id),
            "message": [{"type": "text", "data": {"text": text}}],
        }, "文本")

    def send_private_image(self, user_id, file_path: str):
        """发送私聊图片（用于 gif 表情，线程安全）"""
        if not file_path or not self.enabled:
            return
        if not self._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过发送")
            return
        self.log.info(f"[NapCat] 发送图片 → {user_id}: {file_path}")
        self._submit_send("send_private_msg", {
            "user_id": int(user_id),
            "message": [{"type": "image", "data": {"file": self._to_file_uri(file_path)}}],
        }, "图片")

    def _submit_send(self, action: str, params: dict, label: str):
        """提交发送协程到事件循环，异常与结果在协程内部记录（避免静默吞掉）"""
        try:
            asyncio.run_coroutine_threadsafe(
                self._send_and_log(action, params, label), self.loop
            )
        except Exception:
            self.log.exception(f"提交发送{label}失败")

    async def _send_and_log(self, action: str, params: dict, label: str):
        """发送 OneBot action 并等待响应，记录成功/失败与 retcode"""
        try:
            echo = self._next_echo()
            resp = await self._call_action(echo, action, params)
        except Exception as e:
            self.log.exception(f"[NapCat] 发送{label}异常: {e}")
            return
        if resp is None:
            self.log.warning(f"[NapCat] 发送{label}无响应（超时或连接已断开）")
            return
        retcode = resp.get("retcode")
        if retcode not in (0, "0", None):
            msg = resp.get("msg") or resp.get("wording") or resp.get("message") or str(resp)
            self.log.error(f"[NapCat] 发送{label}失败: retcode={retcode}, {msg}")
        else:
            mid = (resp.get("data") or {}).get("message_id", "")
            self.log.info(f"[NapCat] 发送{label}成功 message_id={mid}")

    def call_action_sync(self, action: str, params: dict, timeout: float = 5.0):
        """同步调用 OneBot API（供 get_friendlist 等主动获取用）"""
        if not self.enabled:
            return None
        if not self._wait_loop_ready(timeout=timeout):
            self.log.warning(f"NapCat 事件循环未就绪，调用失败: {action}")
            return None
        echo = self._next_echo()
        try:
            fut = asyncio.run_coroutine_threadsafe(self._call_action(echo, action, params), self.loop)
            return fut.result(timeout=timeout)
        except Exception:
            self.log.exception(f"调用 NapCat API 失败: {action}")
            return None

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

    @staticmethod
    def _to_file_uri(file_path: str) -> str:
        """本地文件路径转 file URI（供 NapCat image 段发送）"""
        import pathlib
        path = pathlib.Path(file_path)
        if path.is_absolute() and "://" not in file_path:
            return path.as_uri()
        return file_path
