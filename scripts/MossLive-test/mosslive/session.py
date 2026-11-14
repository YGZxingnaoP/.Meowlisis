# -*- coding: utf-8 -*-
# scripts/MossLive-test/mosslive/session.py
# MOSS-Live 实时会话客户端（/v1/realtime）：
#   - WebSocket 握手时把 API Key 放在 Authorization 头（浏览器原生 WebSocket 做不到，所以用 Python）；
#   - attach_session → change_voice → session.update → media.mode/media.configure → 开始收发；
#   - 上行：麦克风 16k PCM（0x00 前缀）+ 屏幕 JPEG（0x02 前缀，tagged-v1）；
#   - 下行：文本事件 + PCM 音频；按实际播放进度发送播放回执；
#   - 工具调用：执行本地工具 → conversation.item.create → conversation.item.created → response.create。
#
# 本轮不接短期记忆/长期记忆，也不启用 client delegation。

import asyncio
import json
import time
import traceback
from urllib.parse import quote

import websockets

from .audio import MicCapture, PlaybackEngine
from .screen import ScreenCapture
from .tools import ToolBox


class ProtocolError(Exception):
    """协议/配置导致的致命错误"""


class MossLiveSession:
    def __init__(self, cfg, prompt_bundle, voice_selection, console):
        self.cfg = cfg
        self.prompt = prompt_bundle
        self.voice = voice_selection
        self.console = console
        self.tools = ToolBox(cfg, console)
        self.screen = ScreenCapture(cfg.screen, console, cfg.local_path(cfg.screen.get("frames_dir") or "frames"))

        self.ws = None
        self.session_id = ""
        self.playback = None
        self.mic = None

        self._loop = None
        self._json_q = None
        self._audio_q = None
        self._screen_q = None
        self._stop_event = None
        self._bg_tasks = []
        self._ready = False
        self._fatal = None
        self._closing = False
        self._send_receipts = str(cfg.session.get("playback") or "client") == "client"
        self._executed_calls = set()
        self._pending_calls = set()
        self._confirmed_calls = []
        self._confirm_task = None
        self._awaiting_voice = False
        self._voice_fallback = str(cfg.voice.get("fallback_name") or "").strip()
        self._voice_fallback_tried = False
        self._last_partial = ""

    # ---------- URL ----------

    def _url(self) -> str:
        base = str(self.cfg.api.get("realtime_url") or "")
        params = [f"model={quote(str(self.cfg.api.get('model') or ''))}"]
        user = str(self.cfg.api.get("user") or "").strip()
        if user:
            params.append(f"user={quote(user)}")
        sep = "&" if "?" in base else "?"
        return base + sep + "&".join(params)

    # ---------- 主流程 ----------

    async def run(self) -> str:
        self._loop = asyncio.get_running_loop()
        self._json_q = asyncio.Queue()
        self._audio_q = asyncio.Queue(maxsize=64)
        self._screen_q = asyncio.Queue(maxsize=1)
        self._stop_event = asyncio.Event()

        key = self.cfg.require_api_key()
        url = self._url()
        self.console.info(f"连接 {url}")
        headers = {
            "Authorization": f"Bearer {key}",
            "User-Agent": "Meowlisis-MossLive-test/1.0",
        }
        try:
            self.ws = await websockets.connect(
                url,
                additional_headers=headers,
                max_size=None,
                proxy=self.cfg.api.get("proxy") or None,
                open_timeout=int(self.cfg.api.get("connect_timeout_sec") or 20),
                ping_interval=20,
                ping_timeout=20,
            )
        except Exception as e:
            raise ProtocolError(f"WebSocket 连接失败: {e}") from e

        self.console.info("WebSocket 已连接，发送 attach_session")
        tasks = [
            asyncio.create_task(self._receiver(), name="receiver"),
            asyncio.create_task(self._json_sender(), name="json-sender"),
            asyncio.create_task(self._audio_sender(), name="audio-sender"),
            asyncio.create_task(self._screen_sender(), name="screen-sender"),
            asyncio.create_task(self._keepalive(), name="keepalive"),
        ]
        attach = {"action": "attach_session", "session_id": None}
        memory_scope = str(self.cfg.session.get("memory_scope") or "session")
        if memory_scope in ("session", "user"):
            attach["memory_scope"] = memory_scope
        self._send_json(attach)

        try:
            await self._stop_event.wait()
        finally:
            self._closing = True
            # 先停设备线程，再收尾异步任务，避免线程在事件循环关闭后还往里塞数据
            self._cleanup_threads()
            for task in tasks + self._bg_tasks:
                task.cancel()
            try:
                await asyncio.gather(*(tasks + self._bg_tasks), return_exceptions=True)
            except BaseException:
                pass
            try:
                await self.ws.close()
            except BaseException:
                pass

        if self._fatal:
            raise self._fatal
        return self.session_id

    # ---------- 发送 ----------

    def _send_json(self, obj: dict):
        if self._json_q is not None:
            try:
                self._json_q.put_nowait(obj)
            except Exception:
                pass

    async def _json_sender(self):
        try:
            while True:
                obj = await self._json_q.get()
                await self.ws.send(json.dumps(obj, ensure_ascii=False))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self._closing:
                self.console.error(f"发送 JSON 失败: {e}")
            self._stop_event.set()

    async def _audio_sender(self):
        try:
            while True:
                payload = await self._audio_q.get()
                await self.ws.send(payload)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self._closing:
                self.console.error(f"发送音频失败: {e}")
            self._stop_event.set()

    async def _screen_sender(self):
        try:
            while True:
                payload = await self._screen_q.get()
                await self.ws.send(payload)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self._closing:
                self.console.error(f"发送画面失败: {e}")
            self._stop_event.set()

    async def _keepalive(self):
        try:
            while True:
                await asyncio.sleep(15)
                if not self._closing:
                    self._send_json({"action": "ping", "timestamp": int(time.time() * 1000)})
        except asyncio.CancelledError:
            raise

    # ---------- 采集回调（线程 → 事件循环） ----------

    def _push_audio(self, pcm: bytes):
        if not self._ready or self._audio_q is None:
            return
        payload = b"\x00" + pcm
        if self._audio_q.full():
            try:
                self._audio_q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._audio_q.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    def _push_screen(self, payload: bytes):
        if not self._ready or self._screen_q is None:
            return
        if self._screen_q.full():
            try:
                self._screen_q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._screen_q.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    def _emit_thread_event(self, event: dict):
        """播放线程的回执 → 事件循环"""
        if not self._send_receipts:
            return
        if self._loop is None or self._loop.is_closed():
            return
        try:
            self._loop.call_soon_threadsafe(self._json_q.put_nowait, event)
        except Exception:
            pass

    # ---------- 接收 ----------

    async def _receiver(self):
        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    self._on_binary(message)
                else:
                    await self._handle_event(json.loads(message))
        except asyncio.CancelledError:
            raise
        except websockets.ConnectionClosed as e:
            if not self._closing:
                self.console.warn(f"连接已关闭: code={getattr(e, 'code', '?')} "
                                  f"reason={getattr(e, 'reason', '') or '（无）'}")
        except ProtocolError as e:
            self._fatal = e
            self.console.error(str(e))
        except Exception as e:
            self._fatal = ProtocolError(f"事件处理异常: {e}")
            self.console.error(f"事件处理异常: {e}")
            self.console.debug(traceback.format_exc())
        finally:
            if self._stop_event is not None:
                self._stop_event.set()

    def _on_binary(self, payload: bytes):
        if not payload:
            return
        if self.playback is None:
            self.console.warn("尚未开始播放，收到音频已丢弃")
            return
        self.playback.feed(payload)

    async def _handle_event(self, msg: dict):
        action = str(msg.get("action") or "")
        data = msg.get("data") or {}
        if action == "session_attached":
            self.console.start_session(str(data.get("session_id") or ""))
        self.console.event(action, data)

        if action == "session_attached":
            self.session_id = str(data.get("session_id") or "")
            self.console.info(
                f"会话已建立: {self.session_id}（记忆范围={data.get('memory_scope')}，"
                f"委派={data.get('delegation')}）"
            )
            self._after_attached()

        elif action == "voice_changed":
            self._awaiting_voice = False
            self.console.info(f"音色已切换: {data.get('name')}")
            if self.voice.voice_id and data.get("name") != self.voice.voice_id:
                self.console.warn("服务端返回的音色与请求不一致，继续使用返回结果")
            self._send_session_update()

        elif action == "session.updated":
            err = str(data.get("error") or "")
            if err:
                raise ProtocolError(f"session.update 失败: {err}")
            self.console.info(f"会话配置已生效，工具={data.get('tools')}")
            self._send_json({"action": "media.mode", "binary_protocol": "tagged-v1"})
            self._send_json(self._media_configure_payload())

        elif action == "media.configured":
            err = str(data.get("error") or "")
            if err:
                raise ProtocolError(f"media.configure 失败: {err}")
            await self._start_media(data)

        elif action == "input.transcript.updated":
            text = str(data.get("text") or "")
            if self.cfg.log.get("show_partial") and text and text != self._last_partial:
                self._last_partial = text
                self.console.user_text(text, final=False)

        elif action == "input.transcript.done":
            text = str(data.get("text") or "")
            self._last_partial = ""
            if text:
                self.console.user_text(text)

        elif action == "input.transcript.revised":
            text = str(data.get("text") or "")
            if text:
                self.console.user_text(f"{text}（修订）")

        elif action == "output.transcript.updated":
            text = str(data.get("text") or "")
            if self.cfg.log.get("show_partial") and text and text != self._last_partial:
                self._last_partial = text
                self.console.assistant_text(text, final=False)

        elif action == "output.transcript.done":
            text = str(data.get("text") or "")
            self._last_partial = ""
            if text:
                self.console.assistant_text(text)

        elif action == "response.audio.started":
            self.console.debug(f"回复开始: run_id={data.get('run_id')}")

        elif action == "response.audio.context":
            if self.playback:
                self.playback.set_context(data)

        elif action == "response.audio.done":
            if self.playback:
                self.playback.audio_done(str(data.get("run_id") or ""), str(data.get("turn_id") or ""))

        elif action == "response.audio.stop":
            self.console.info(f"服务端要求停止播放: {data.get('reason') or ''}")
            if self.playback:
                self.playback.stop_run(str(data.get("run_id") or ""), str(data.get("turn_id") or ""))

        elif action == "response.interrupted":
            self.console.info(f"本轮回复被中断: {data.get('reason') or ''}")
            if self.playback:
                self.playback.stop_all(str(data.get("reason") or ""))

        elif action == "response.ended":
            self.console.debug(f"回复结束: status={data.get('status')} run_id={data.get('run_id')}")

        elif action == "response.function_call_arguments.done":
            await self._on_tool_call(data)

        elif action == "response.done":
            # 与参数完成事件可能重复，按 call_id 去重；这里只记录，不重复执行
            self.console.debug("response.done（工具输出汇总）")

        elif action == "conversation.item.created":
            self._on_tool_output_confirmed(data)

        elif action == "error":
            err = data.get("error") or {}
            text = f"{err.get('code')}: {err.get('message')}"
            if self._awaiting_voice:
                self._awaiting_voice = False
                if (not self._voice_fallback_tried and self._voice_fallback
                        and self._voice_fallback != self.voice.voice_id):
                    self._voice_fallback_tried = True
                    self.console.warn(f"音色切换失败（{text}），改用回落音色 {self._voice_fallback}")
                    self._awaiting_voice = True
                    self._send_json({"action": "change_voice", "voice_name": self._voice_fallback})
                    return
                self.console.warn(f"音色切换失败（{text}），改用服务端默认音色")
                self._send_session_update()
                return
            if not self._ready:
                raise ProtocolError(f"服务端返回错误: {text}")
            self.console.error(f"服务端错误: {text}")

        elif action == "session.closing":
            self.console.warn(
                f"服务端即将关闭连接: code={data.get('code')} reason={data.get('reason')} "
                f"可重连={data.get('reconnect')}"
            )

        elif action == "pong":
            sent = data.get("client_timestamp")
            if sent:
                self.console.debug(f"心跳往返约 {int(time.time() * 1000) - int(sent)}ms")
            else:
                self.console.debug("pong")

        elif action in ("input.speech.started", "input.speech.stopped"):
            self.console.debug("用户说话开始" if action.endswith("started") else "用户说话停止")

        elif action in ("session.thinking.appended", "session.commentary.appended",
                        "session.instructions.appended"):
            self.console.debug(action)

        else:
            self.console.debug(f"未处理事件: {action}")

    # ---------- 会话初始化 ----------

    def _after_attached(self):
        if self.voice.voice_id:
            self.console.info(f"切换音色: {self.voice.voice_id}")
            self._awaiting_voice = True
            self._send_json({"action": "change_voice", "voice_name": self.voice.voice_id})
        else:
            self._send_session_update()

    def _send_session_update(self):
        tools = self.tools.definitions()
        session = {
            "persona": {
                "name": self.prompt.persona_name,
                "prompt": self.prompt.persona,
            },
            "instructions": self.prompt.instructions,
        }
        if tools:
            session["tools"] = tools
        self.console.info(f"提交会话配置（工具 {len(tools)} 个）")
        self._send_json({"action": "session.update", "session": session})

    def _media_configure_payload(self) -> dict:
        s = self.cfg.session
        payload = {
            "action": "media.configure",
            "profile": str(s.get("profile") or "standard"),
            "playback": str(s.get("playback") or "client"),
        }
        out = s.get("output_audio")
        if isinstance(out, dict) and out:
            payload["output_audio"] = out
        inp = s.get("input_audio")
        if isinstance(inp, dict) and inp:
            payload["input_audio"] = inp
        video = s.get("video")
        if isinstance(video, dict) and video:
            payload["video"] = video
        return payload

    async def _start_media(self, data: dict):
        out = data.get("output_audio") or {}
        fmt = str(out.get("format") or "pcm16")
        rate = int(out.get("sample_rate") or self.cfg.audio.get("output_rate") or 48000)
        if fmt != "pcm16":
            raise ProtocolError(
                f"本测试只做 pcm16 下行播放，服务端返回 {fmt}。"
                "请把 session.output_audio.format 设为 pcm16 或换回 standard 预设。"
            )
        self.console.info(
            f"媒体已配置: 上行={data.get('input_audio')} 下行={out} "
            f"画面={data.get('video')} 回执={data.get('playback')}"
        )

        # 扬声器/播放
        self.playback = PlaybackEngine(
            device=int(self.cfg.audio.get("output_device") or -1),
            volume=float(self.cfg.audio.get("volume") or 1.0),
            source_rate=rate,
            on_event=self._emit_thread_event,
            console=self.console,
            simulate=not bool(self.cfg.audio.get("output_enabled", True)),
        )
        self.playback.start()

        self._send_json(self._client_context_payload())

        # 屏幕
        if self.screen.enabled:
            self.screen.configure(data.get("video") or {})
            self._send_json({"action": "video.state", "source": "screen", "enabled": True})
            self._send_json({"action": "video.stream_focus", "source": "screen"})
            self.screen.start(self._loop, self._push_screen)
        else:
            self.console.info("屏幕推流已关闭（screen.enabled=false）")

        # 麦克风（关闭时仍持续发送静音，保持时间线；接口允许关麦）
        mic_enabled = bool(self.cfg.audio.get("input_enabled", True))
        self._send_json({"action": "mic_state", "enabled": mic_enabled})
        if mic_enabled:
            self.mic = MicCapture(
                device=int(self.cfg.audio.get("input_device") or -1),
                frame_ms=int(self.cfg.audio.get("frame_ms") or 20),
                target_rate=int(self.cfg.audio.get("input_rate") or 16000),
                on_frame=self._push_audio,
                console=self.console,
            )
            if not self.mic.start():
                self.console.warn("麦克风不可用，改为持续发送静音（仍可听助手说话）")
                self._start_silence_feed()
        else:
            self.console.info("麦克风已关闭（audio.input_enabled=false），不发送上行音频")

        self._ready = True
        self.console.info("会话就绪，可以说话了。按 Ctrl+C 结束。")

    def _client_context_payload(self) -> dict:
        s = self.cfg.session
        ctx = {"time_zone": str(s.get("time_zone") or "Asia/Shanghai")}
        loc = s.get("location")
        if isinstance(loc, dict) and "latitude" in loc and "longitude" in loc:
            ctx["location"] = {"latitude": float(loc["latitude"]), "longitude": float(loc["longitude"])}
        return {"action": "client_context.update", "context": ctx}

    def _start_silence_feed(self):
        """没有麦克风时按 20ms 节奏发静音，让服务端的输入时间线连续"""
        frame_ms = int(self.cfg.audio.get("frame_ms") or 20)
        zero = b"\x00" * (int(16000 * frame_ms / 1000) * 2)

        async def _feed():
            try:
                while True:
                    await asyncio.sleep(frame_ms / 1000.0)
                    self._push_audio(zero)
            except asyncio.CancelledError:
                raise

        self._bg_tasks.append(asyncio.create_task(_feed(), name="silence-feed"))

    # ---------- 工具调用 ----------

    async def _on_tool_call(self, data: dict):
        call_id = str(data.get("call_id") or "")
        name = str(data.get("name") or "")
        if not call_id:
            return
        if call_id in self._executed_calls:
            return
        self._executed_calls.add(call_id)
        raw_args = data.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            if not isinstance(args, dict):
                args = {}
        except Exception:
            args = {"_raw": raw_args}
        self.console.tool_call(name, args)
        result = await asyncio.to_thread(self.tools.execute, name, args)
        self.console.tool_result(name, result)
        self._pending_calls.add(call_id)
        self._send_json({
            "action": "conversation.item.create",
            "item": {"type": "function_call_output", "call_id": call_id, "output": result},
        })

    def _on_tool_output_confirmed(self, data: dict):
        item = data.get("item") or {}
        if item.get("type") != "function_call_output":
            return
        call_id = str(item.get("call_id") or "")
        if call_id not in self._pending_calls:
            return
        self._pending_calls.discard(call_id)
        self._confirmed_calls.append(call_id)
        # 同一轮可能有多个工具调用：等一小会儿凑齐，再一次性续答
        if self._confirm_task is None:
            self._confirm_task = asyncio.create_task(self._flush_confirmations())
            self._bg_tasks.append(self._confirm_task)

    async def _flush_confirmations(self):
        try:
            await asyncio.sleep(0.08)
            call_ids = self._confirmed_calls[:]
            self._confirmed_calls.clear()
            if call_ids and not self._closing:
                self._send_json({"action": "response.create", "response": {"call_ids": call_ids}})
        except asyncio.CancelledError:
            raise
        finally:
            self._confirm_task = None

    # ---------- 清理 ----------

    def _cleanup_threads(self):
        if self.mic:
            self.mic.close()
            self.mic = None
        if self.playback:
            self.playback.close()
            self.playback = None
        self.screen.close()
