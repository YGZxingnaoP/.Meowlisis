# -*- coding: utf-8 -*-
# func/toolbox/napcat/napcat_core.py
# NapCat 核心：作为客户端连接 NapCat OneBot v11 正向 WebSocket，收发数据与事件

import asyncio
import json
import random
import threading
from typing import Optional, Callable

import websockets

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.napcat.config import TBNapCatConfig


@singleton
class TBNapCatCore:
    """NapCat 控制核心：正向 WS 客户端，负责连接、收事件、发 API 请求"""

    # 消息聚合缓冲：随机等待区间（秒）与连续等待循环上限
    BUFFER_WAIT_MIN = 5.0
    BUFFER_WAIT_MAX = 15.0
    BUFFER_MAX_ROUNDS = 10

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

        # 私聊消息聚合缓冲：user_id -> {"username","user_id","self_id","texts","count","timer"}
        self._buffer_lock = threading.Lock()
        self._buffers = {}

        # 私聊消息回调（默认指向内部串联处理：解析→缓冲→拉历史→TBoxCore.receive_qq）
        self.on_private_message: Optional[Callable[[dict], None]] = self._handle_private_message
        # 群聊消息回调（默认指向内部串联处理：解析→黑名单→TBoxCore.receive_group）
        self.on_group_message: Optional[Callable[[dict], None]] = self._handle_group_message
        # 戳一戳回调（默认指向内部处理：检测连续被戳）
        self.on_poke: Optional[Callable[[dict], None]] = self._handle_poke
        # 消息解析与历史拉取
        from func.toolbox.napcat.message.get_message import TBGetMessage
        from func.toolbox.napcat.message.get_record import TBGetRecord
        from func.toolbox.napcat.groupchat.get_group_message import TBGetGroupMessage
        self.get_message = TBGetMessage()
        self.get_record = TBGetRecord()
        self.get_group_message = TBGetGroupMessage()
        # 群名缓存（group_id -> group_name），避免每条消息重复调 API
        self._group_name_cache = {}
        self._group_name_lock = threading.Lock()

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
        # 清理所有待发送的消息缓冲定时器
        self._clear_buffers()
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
        if self.config.debug_event_dump and data.get("post_type"):
            self._dump_event(data)
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

    # ==================== 私聊消息处理（聚合缓冲） ====================
    def _handle_private_message(self, event: dict):
        """解析私聊消息并送入聚合缓冲（延迟合并后统一交给 AI）"""
        try:
            # 私聊回复开关
            if not self.config.private_reply_enabled:
                return
            # 消息打断戳一戳计数（私聊）
            try:
                user_id = event.get("user_id") or (event.get("sender") or {}).get("user_id")
                from func.toolbox.napcat.groupchat.poke_detector import TBPokeDetector
                TBPokeDetector().on_interrupt("private", str(user_id or ""))
            except Exception:
                pass
            # 图片检测：私聊发图必看（不再做 vision_decide 判断）
            from func.toolbox.napcat.image.image_search import TBImageSearch
            images = TBImageSearch.extract_images(event.get("message"))
            if images:
                user_id = event.get("user_id") or (event.get("sender") or {}).get("user_id")
                self_id = event.get("self_id")
                username = str((event.get("sender") or {}).get("nickname") or user_id or "")
                text = TBImageSearch.text_from_segments(event.get("message"))
                # 图片落地本地缓存区（避免直接用带鉴权的 url）
                from func.toolbox.meowvision.config import TBVisionConfig
                cache_dir = TBVisionConfig().cache_dir
                image_paths = TBImageSearch.to_local_paths(images, cache_dir)
                if image_paths:
                    from func.toolbox.meowvision.vision_core import TBVisionCore
                    # 幻梦（机器人）发的图不写记忆，其余用户图正常写记忆
                    is_bot = self._is_bot_user(user_id)
                    result = TBVisionCore().process(
                        image_paths, text, username,
                        need_description=True, write_memory=not is_bot,
                    )
                    vision_reply = (result.get("reply") or "").strip()
                    if vision_reply:
                        self.send_private_text(str(user_id), vision_reply)
                        self.log.info(f"[视觉] 私聊图片视觉回复已发: {vision_reply[:30]}")
                return
            parsed = self.get_message.parse(event)
            if not parsed or not parsed.get("text"):
                return
            self_id = event.get("self_id")
            self._buffer_message(parsed, self_id)
        except Exception:
            self.log.exception("处理私聊消息异常")

    # ==================== 戳一戳处理 ====================
    def _handle_poke(self, event: dict):
        """处理戳一戳通知：检测连续被戳，达到阈值触发角色发牢骚

        NapCat 戳一戳事件字段：
        - 群聊：post_type=notice, sub_type=poke, group_id, user_id(戳的人), target_id(被戳的人)
        - 私聊：post_type=notice, sub_type=poke, user_id(戳的人), sender_id, target_id(被戳的人)
        无 message_type 字段，通过是否有 group_id 区分群/私聊。
        """
        try:
            target_id = str(event.get("target_id", "") or "")
            self_id = str(event.get("self_id", "") or "")
            # 只有被戳对象是自己才计数
            if target_id and self_id and target_id != self_id:
                return

            group_id = str(event.get("group_id", "") or "")
            if group_id:
                # 群聊戳一戳
                message_type = "group"
                session_id = group_id
                user_id = str(event.get("user_id", "") or "")
            else:
                # 私聊戳一戳
                message_type = "private"
                user_id = str(event.get("user_id", "") or event.get("sender_id", "") or "")
                session_id = user_id

            from func.toolbox.napcat.groupchat.poke_detector import TBPokeDetector
            triggered = TBPokeDetector().on_poke(message_type, session_id, user_id)
            if triggered:
                # 补充 event 里的 user_id 供发牢骚发送使用
                event["_poke_user_id"] = user_id
                self._poke_complain(message_type, session_id, event)
        except Exception:
            self.log.exception("处理戳一戳异常")

    def _poke_complain(self, message_type: str, session_id: str, event: dict):
        """触发戳一戳发牢骚：LLM 流式生成牢骚（仅前后置词），分段发送并写记忆"""
        try:
            from func.pipeline.system_prompt import SystemPromptBridge
            from func.toolbox.napcat.llm.napcat_llm import TBNapCatLLM

            # 仅前后置词（后置词=被戳烦了骂他们），不含角色卡/用户记忆/日期/摘要
            system_prompt = SystemPromptBridge().get_poke_prompt()

            # 发送回调：流式分段发到群/私聊
            def on_segment(seg: str):
                if not seg:
                    return
                if message_type == "group":
                    self.send_group_text(session_id, seg)
                else:
                    user_id = str(event.get("_poke_user_id", "") or event.get("user_id", "") or "")
                    if user_id:
                        self.send_private_text(user_id, seg)

            messages = [
                {"role": "user", "content": "你被连续戳了好几下，快发牢骚骂他们。"},
            ]
            complain_text = TBNapCatLLM().reply_stream(system_prompt, messages, on_segment)
            if not complain_text:
                return

            # 写记忆（assistant 身份）
            from func.pipeline.short_memory import ShortMemory
            if message_type == "group":
                ShortMemory().save({
                    "role": "assistant",
                    "content": f"【来自QQ群的消息】{complain_text}",
                    "type": "qq_groupchat",
                }, self.config.group_memory_limit)
            else:
                ShortMemory().save({
                    "role": "assistant",
                    "content": f"【来自QQ的消息】{complain_text}",
                    "type": "qq_response",
                }, self.config.short_mem_rounds)
            self.log.info(f"[戳一戳] 已发牢骚: {complain_text[:30]}")
        except Exception:
            self.log.exception("戳一戳发牢骚失败")

    # ==================== 群聊消息处理 ====================
    def _handle_group_message(self, event: dict):
        """解析群聊消息并送入 TBoxCore.receive_group（黑名单/主动回复逻辑在内部处理）"""
        try:
            # 消息打断戳一戳计数（群聊）
            try:
                group_id = event.get("group_id")
                from func.toolbox.napcat.groupchat.poke_detector import TBPokeDetector
                TBPokeDetector().on_interrupt("group", str(group_id or ""))
            except Exception:
                pass
            parsed = self.get_group_message.parse(event)
            if not parsed:
                return
            group_id = str(parsed.get("group_id", ""))
            group_name = self._resolve_group_name(group_id)
            parsed["group_name"] = group_name
            # 顺带记录 QQ 号 → 昵称映射（供 @ 触发时加载稳定用户档案）
            try:
                from func.toolbox.napcat.groupchat.user_nickname import TBUserNicknameMap
                sender = (event.get("sender") or {})
                TBUserNicknameMap().observe(
                    parsed.get("user_id"),
                    card=sender.get("card", ""),
                    nickname=sender.get("nickname", ""),
                )
            except Exception:
                self.log.exception("记录 QQ 昵称映射失败")
            if self.get_group_message.in_blacklist(group_name):
                self.log.info(f"[NapCat群聊] 群 {group_name}({group_id}) 命中黑名单，跳过")
                return
            from func.toolbox.toolbox_core import TBoxCore
            TBoxCore().receive_group(parsed)
        except Exception:
            self.log.exception("处理群聊消息异常")

    def _dump_event(self, data: dict):
        """把原始事件追加写入 .temp/napcat_raw_events.jsonl（一行一个 JSON）"""
        try:
            import os
            os.makedirs(".temp", exist_ok=True)
            with open(".temp/napcat_raw_events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _is_bot_user(self, user_id) -> bool:
        """判断发送者是否为已配置的群机器人（如幻梦）"""
        try:
            uid = str(user_id or "")
            for qq in (self.config.group_bots or {}).values():
                if str(qq) == uid:
                    return True
        except Exception:
            pass
        return False

    def _resolve_group_name(self, group_id: str) -> str:
        """解析群名（缓存 + get_group_info API）"""
        with self._group_name_lock:
            cached = self._group_name_cache.get(group_id)
            if cached:
                return cached
        name = ""
        try:
            ret = self.call_action_sync("get_group_info", {"group_id": int(group_id)})
            if isinstance(ret, dict):
                data = ret.get("data") or {}
                name = str(data.get("group_name", "") or "").strip()
        except Exception:
            self.log.exception(f"获取群信息失败: {group_id}")
        if not name:
            name = group_id
        with self._group_name_lock:
            self._group_name_cache[group_id] = name
        return name

    def _buffer_message(self, parsed: dict, self_id):
        """将用户消息放入缓冲：无新消息则随机 5~15 秒后发送，有新消息则合并重新计时，上限 10 次"""
        user_id = parsed["user_id"]
        to_flush = None
        with self._buffer_lock:
            buf = self._buffers.get(user_id)
            if buf is None:
                buf = {
                    "username": parsed["username"],
                    "user_id": user_id,
                    "self_id": self_id,
                    "texts": [],
                    "count": 0,
                    "timer": None,
                }
                self._buffers[user_id] = buf
            # 合并文本，更新身份
            buf["texts"].append(parsed["text"])
            buf["username"] = parsed["username"]
            buf["self_id"] = self_id
            # 取消旧定时器
            if buf["timer"] is not None:
                buf["timer"].cancel()
                buf["timer"] = None
            buf["count"] += 1
            # 达到循环上限：立即发送，不再等待
            if buf["count"] >= self.BUFFER_MAX_ROUNDS:
                to_flush = self._buffers.pop(user_id, None)
                self.log.info(f"[NapCat缓冲] 用户 {user_id} 达到上限 {self.BUFFER_MAX_ROUNDS} 次，立即发送")
            else:
                wait = random.uniform(self.BUFFER_WAIT_MIN, self.BUFFER_WAIT_MAX)
                timer = threading.Timer(wait, self._on_buffer_timeout, args=(user_id, buf["count"]))
                timer.daemon = True
                buf["timer"] = timer
                timer.start()
                self.log.info(
                    f"[NapCat缓冲] 用户 {user_id} 第 {buf['count']} 条消息，{wait:.1f} 秒后无新消息则发送"
                )
        if to_flush:
            self._send_buffered(to_flush)

    def _on_buffer_timeout(self, user_id: str, count: int):
        """缓冲定时器到期：若无新消息（count 未变），取出并发送"""
        to_flush = None
        with self._buffer_lock:
            buf = self._buffers.get(user_id)
            if buf is None or buf["count"] != count:
                # 期间来了新消息，已重新计时，忽略本次超时
                return
            to_flush = self._buffers.pop(user_id, None)
        if to_flush:
            self.log.info(f"[NapCat缓冲] 用户 {user_id} 停顿超时，发送合并消息（共 {len(to_flush['texts'])} 条）")
            self._send_buffered(to_flush)

    def _send_buffered(self, buf: dict):
        """将缓冲中的合并消息发送给 AI（重新拉取最新历史作为短期记忆）"""
        username = buf["username"]
        user_id = buf["user_id"]
        self_id = buf["self_id"]
        text = "，".join(t for t in buf["texts"] if t and t.strip())
        if not text.strip():
            return
        try:
            short_memory = self.get_record.fetch(user_id, self_id)
            from func.toolbox.toolbox_core import TBoxCore
            TBoxCore().receive_qq(username, user_id, text, short_memory)
        except Exception:
            self.log.exception("发送缓冲消息异常")

    def _clear_buffers(self):
        """清空所有缓冲并取消定时器（停止时调用）"""
        with self._buffer_lock:
            for buf in self._buffers.values():
                if buf.get("timer") is not None:
                    buf["timer"].cancel()
            self._buffers.clear()

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

    def send_group_text(self, group_id, text: str):
        """发送群聊文本（线程安全，异步发送）"""
        if not text or not self.enabled:
            return
        if not self._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过群发送")
            return
        self.log.info(f"[NapCat] 发送群文本 → {group_id}: {text[:40]}")
        self._submit_send("send_group_msg", {
            "group_id": int(group_id),
            "message": [{"type": "text", "data": {"text": text}}],
        }, "群文本")

    def send_group_image(self, group_id, file_path: str):
        """发送群聊图片（线程安全）"""
        if not file_path or not self.enabled:
            return
        if not self._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过群图片发送")
            return
        self.log.info(f"[NapCat] 发送群图片 → {group_id}: {file_path}")
        self._submit_send("send_group_msg", {
            "group_id": int(group_id),
            "message": [{"type": "image", "data": {"file": self._to_file_uri(file_path)}}],
        }, "群图片")

    def send_group_file(self, group_id, file_path: str):
        """发送群聊文件（线程安全）"""
        if not file_path or not self.enabled:
            return
        if not self._wait_loop_ready():
            self.log.warning("NapCat 事件循环未就绪，跳过群文件发送")
            return
        self.log.info(f"[NapCat] 发送群文件 → {group_id}: {file_path}")
        self._submit_send("send_group_msg", {
            "group_id": int(group_id),
            "message": [{"type": "file", "data": {"file": file_path}}],
        }, "群文件")

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
        """本地文件路径转 file URI（供 NapCat image 段发送）

        绝对路径和相对路径都转成 file:/// 绝对路径，避免 NapCat 无法识别相对路径。
        """
        import pathlib
        if "://" in file_path or file_path.startswith("data:"):
            return file_path
        path = pathlib.Path(file_path)
        if not path.is_absolute():
            path = path.resolve()
        return path.as_uri()
