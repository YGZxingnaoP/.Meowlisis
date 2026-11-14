# -*- coding: utf-8 -*-
# scripts/MossLive-test/mock_server.py
# 本地协议自测用的假 MOSS-Live 服务：不需要 API Key，验证客户端能不能把
# 握手 / 配置 / 上行音频 / 屏幕帧 / 播放回执 / 工具调用 / 打断回执 全跑通。
#
# 用法：先起假服务，再用 mock_config.json 跑客户端：
#   runtime\311\python.exe scripts\MossLive-test\mock_server.py
#   runtime\311\python.exe scripts\MossLive-test\mosslive_test.py --config scripts\MossLive-test\mock_config.json
#
# 只模拟协议时序，不理解语音内容；真机联调请直接用 config.json。

import argparse
import asyncio
import io
import json
import math
import sys
import traceback

from PIL import Image
from websockets.asyncio.server import serve


FAILS = []
COUNTS = {"audio": 0, "screen": 0, "camera": 0, "other": 0}
SCREEN_SIZES = []
EVENTS = []


def fail(msg):
    FAILS.append(msg)
    print("FAIL:", msg, flush=True)


def check(cond, msg):
    if not cond:
        fail(msg)


class Collector:
    def __init__(self):
        self.q = asyncio.Queue()

    async def reader(self, ws):
        async for msg in ws:
            if isinstance(msg, bytes):
                self._binary(msg)
                continue
            ev = json.loads(msg)
            EVENTS.append(ev)
            await self.q.put(ev)

    @staticmethod
    def _binary(msg):
        tag = msg[0]
        if tag == 0x00:
            COUNTS["audio"] += 1
            if not (300 <= len(msg) - 1 <= 4000):
                fail(f"上行音频帧长度异常: {len(msg) - 1}")
        elif tag == 0x02:
            COUNTS["screen"] += 1
            body = msg[1:]
            if not body.startswith(b"\xff\xd8"):
                fail("屏幕帧不是 JPEG")
            else:
                try:
                    img = Image.open(io.BytesIO(body))
                    SCREEN_SIZES.append(img.size)
                except Exception as e:
                    fail(f"屏幕 JPEG 解码失败: {e}")
        elif tag == 0x01:
            COUNTS["camera"] += 1
        else:
            COUNTS["other"] += 1
            fail(f"未知二进制前缀: {tag}")

    async def wait(self, action, timeout=8.0):
        end = asyncio.get_running_loop().time() + timeout
        while True:
            left = end - asyncio.get_running_loop().time()
            if left <= 0:
                fail(f"等待事件超时: {action}")
                return None
            try:
                ev = await asyncio.wait_for(self.q.get(), timeout=left)
            except asyncio.TimeoutError:
                fail(f"等待事件超时: {action}")
                return None
            if ev.get("action") == action:
                return ev


async def send(ws, obj):
    await ws.send(json.dumps(obj, ensure_ascii=False))


def pcm_tone(seconds, rate=48000):
    n = int(seconds * rate)
    out = bytearray()
    for i in range(n):
        value = int(3000 * math.sin(2 * math.pi * 440 * i / rate))
        out += value.to_bytes(2, "little", signed=True)
    return bytes(out)


async def handler(ws, expected_voice, expect_tools):
    path = ws.request.path
    auth = ws.request.headers.get("Authorization", "")
    ok_model = "model=moss-live-1.0" in path
    check("/v1/realtime" in path and ok_model, f"路径/模型参数不对: {path}")
    check(auth.startswith("Bearer ") and len(auth) > 8, f"Authorization 头不对: {auth}")

    col = Collector()
    reader = asyncio.create_task(col.reader(ws))
    try:
        attach = await col.wait("attach_session", 5)
        check(attach is not None, "没有收到 attach_session")
        check(attach and attach.get("session_id") in (None, ""), "attach_session.session_id 应为空")
        await send(ws, {"action": "session_attached",
                        "data": {"session_id": "mock-session-1", "memory_scope": "session",
                                 "delegation": "none"}})

        cv = await col.wait("change_voice", 5)
        check(cv is not None and cv.get("voice_name") == expected_voice,
              f"change_voice 不对: {cv}")
        await send(ws, {"action": "voice_changed", "data": {"name": expected_voice}})

        su = await col.wait("session.update", 5)
        session = (su or {}).get("session") or {}
        check(bool((session.get("persona") or {}).get("prompt")), "session.update 缺 persona.prompt")
        check(bool(session.get("instructions")), "session.update 缺 instructions")
        names = [t.get("name") for t in (session.get("tools") or [])]
        check(len(names) == len(expect_tools), f"工具数量不对: {names}")
        for name in expect_tools:
            check(name in names, f"缺少工具: {name}")
        for tool in session.get("tools") or []:
            if tool.get("name") == "search_files":
                check(tool.get("execution_mode") == "async_query", "search_files 应为 async_query")
                check(tool.get("read_only") is True, "search_files 应 read_only=true")
        print("PERSONA_LEN", len((session.get("persona") or {}).get("prompt", "")),
              "INSTR_LEN", len(session.get("instructions", "")), flush=True)
        await send(ws, {"action": "session.updated", "data": {"error": "", "tools": names}})

        mm = await col.wait("media.mode", 5)
        check(mm and mm.get("binary_protocol") == "tagged-v1", f"media.mode 不对: {mm}")
        mc = await col.wait("media.configure", 5)
        check(mc and mc.get("profile") == "standard", f"media.configure 不对: {mc}")
        check((mc or {}).get("playback") == "client", "playback 应为 client")

        await send(ws, {"action": "media.configured", "data": {
            "profile": "standard",
            "output_audio": {"format": "pcm16", "sample_rate": 48000, "channels": 1,
                             "framing": "s16le"},
            "input_audio": {"format": "pcm16", "sample_rate": 16000, "channels": 1,
                            "framing": "s16le"},
            "video": {"max_long_side": 512, "jpeg_quality": 0.75, "interval_ms": 500},
            "playback": "client",
            "available": {},
            "error": "",
        }})

        seen = set()
        deadline = asyncio.get_running_loop().time() + 5
        while {"video.state", "mic_state", "client_context.update"} - seen:
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0:
                fail(f"初始化控制事件缺失，已收到: {seen}")
                break
            try:
                ev = await asyncio.wait_for(col.q.get(), timeout=left)
            except asyncio.TimeoutError:
                fail(f"初始化控制事件超时，已收到: {seen}")
                break
            seen.add(ev.get("action"))
            if ev.get("action") == "video.state":
                check(ev.get("source") == "screen" and ev.get("enabled") is True,
                      f"video.state 不对: {ev}")
            if ev.get("action") == "mic_state":
                check(ev.get("enabled") is True, f"mic_state 不对: {ev}")
            if ev.get("action") == "client_context.update":
                tz = (ev.get("context") or {}).get("time_zone")
                check(tz == "Asia/Shanghai", f"时区不对: {tz}")

        await asyncio.sleep(1.2)
        check(COUNTS["audio"] >= 30, f"上行音频帧太少: {COUNTS['audio']}")
        check(COUNTS["screen"] >= 1, f"没有收到屏幕帧: {COUNTS['screen']}")
        if SCREEN_SIZES:
            w, h = SCREEN_SIZES[-1]
            check(max(w, h) <= 512, f"屏幕帧长边超限: {w}x{h}")
            print("SCREEN", w, h, flush=True)

        # 第一轮：文本 + 0.6 秒音频 + 播放回执
        await send(ws, {"action": "input.transcript.done", "data": {"text": "测试一下", "turn": "u1"}})
        await send(ws, {"action": "output.transcript.updated",
                        "data": {"text": "我在", "run_id": "run1", "turn_id": "t1"}})
        await send(ws, {"action": "output.transcript.done",
                        "data": {"text": "我在，听到了。", "run_id": "run1", "turn_id": "t1"}})
        await send(ws, {"action": "response.audio.started",
                        "data": {"run_id": "run1", "turn_id": "t1"}})
        await send(ws, {"action": "response.audio.context",
                        "data": {"run_id": "run1", "turn_id": "t1", "chunk_id": "c1"}})
        await ws.send(pcm_tone(0.6))
        await send(ws, {"action": "response.audio.done",
                        "data": {"run_id": "run1", "turn_id": "t1"}})

        chunk_done = await col.wait("playback.chunk.completed", 6)
        check(chunk_done is not None and chunk_done.get("chunk_id") == "c1",
              f"播放回执不对: {chunk_done}")
        complete = await col.wait("playback.completed", 6)
        check(complete is not None and complete.get("run_id") == "run1",
              f"playback.completed 不对: {complete}")
        await send(ws, {"action": "response.ended",
                        "data": {"status": "completed", "run_id": "run1", "turn_id": "t1"}})

        # 工具调用
        await send(ws, {"action": "response.function_call_arguments.done", "data": {
            "type": "response.function_call_arguments.done",
            "response_id": "resp-tool", "item_id": "item-tool", "call_id": "call_1",
            "name": "get_time", "output_index": 0, "arguments": "{}",
        }})
        item = await col.wait("conversation.item.create", 8)
        output = ((item or {}).get("item") or {}).get("output")
        check(bool(output), "工具结果为空")
        try:
            check(json.loads(output).get("ok") is True, f"get_time 结果不对: {output}")
        except Exception:
            fail(f"工具结果不是 JSON: {output}")
        await send(ws, {"action": "conversation.item.created", "data": {
            "type": "conversation.item.created",
            "item": {"id": "out_1", "type": "function_call_output", "call_id": "call_1"},
        }})
        rc = await col.wait("response.create", 5)
        check((rc or {}).get("response", {}).get("call_ids") == ["call_1"],
              f"response.create 不对: {rc}")

        # 打断：播放中途 stop，应回 playback.stopped
        await send(ws, {"action": "response.audio.started",
                        "data": {"run_id": "run2", "turn_id": "t2"}})
        await send(ws, {"action": "response.audio.context",
                        "data": {"run_id": "run2", "turn_id": "t2", "chunk_id": "c2"}})
        await ws.send(pcm_tone(3.0))
        await asyncio.sleep(0.4)
        await send(ws, {"action": "response.audio.stop",
                        "data": {"run_id": "run2", "turn_id": "t2", "reason": "user_speech"}})
        stopped = await col.wait("playback.stopped", 5)
        if stopped:
            played = stopped.get("played_audio_ms", -1)
            check(0 <= played < 3000, f"played_audio_ms 不合理: {played}")
            print("STOPPED", played, flush=True)
        await send(ws, {"action": "response.ended",
                        "data": {"status": "aborted", "run_id": "run2", "turn_id": "t2"}})
        await asyncio.sleep(0.3)
    except Exception as e:
        fail(f"处理异常: {e}")
        traceback.print_exc()
    finally:
        reader.cancel()
        try:
            await reader
        except Exception:
            pass


async def main_async(port: int, voice: str, tools: list):
    print(f"mock listening 127.0.0.1:{port}", flush=True)
    stop = asyncio.Event()

    async def wrapped(ws):
        try:
            await handler(ws, voice, tools)
        finally:
            stop.set()

    async with serve(wrapped, "127.0.0.1", port, max_size=None) as server:
        await stop.wait()
        server.close()
        await server.wait_closed()

    report = {
        "fails": FAILS,
        "counts": COUNTS,
        "screen_sizes": SCREEN_SIZES,
        "events": [e.get("action") for e in EVENTS],
    }
    print("REPORT " + json.dumps(report, ensure_ascii=False), flush=True)
    return 1 if FAILS else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="MOSS-Live 本地假服务（协议自测）")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--voice", default="test-voice", help="mock_config 里 voice.name 的值")
    parser.add_argument("--tools", default="get_time,open_url,list_windows,activate_window,save_note,search_files")
    args = parser.parse_args()
    tools = [x.strip() for x in args.tools.split(",") if x.strip()]
    try:
        return asyncio.run(main_async(args.port, args.voice, tools))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
