# -*- coding: utf-8 -*-
# server/session.py - 单连接识别会话：说话状态/音频累积/整段识别

import asyncio
import json
import os
import re

from audio import save_audio_to_wav


class SenseVoiceSession:
    """维护单连接的说话状态与音频缓冲，说话结束时执行 ASR+声纹并回传"""

    def __init__(self, websocket, sv, ctx):
        self.websocket = websocket
        self.sv = sv
        self.ctx = ctx
        self.audio_buffer = bytearray()
        self.is_speaking = True
        self.wav_name = "mic"
        self.language = "auto"
        self.itn = True
        self.hotwords = {}
        self._rec_lock = None  # 会话级识别串行锁：两句结果按序回传

    def handle_audio(self, audio_chunk: bytes):
        """说话中累积音频帧"""
        if self.is_speaking:
            self.audio_buffer.extend(audio_chunk)

    async def handle_text_message(self, message: dict):
        """处理文本消息：说话状态切换与识别参数更新"""
        if "is_speaking" in message:
            was = self.is_speaking
            self.is_speaking = message["is_speaking"]
            if not was and self.is_speaking:
                self.audio_buffer = bytearray()
                print("客户端开始说话")
                self.ctx.tick("user_start", self.wav_name)
            elif was and not self.is_speaking:
                if len(self.audio_buffer) > 0:
                    buf = bytes(self.audio_buffer)
                    self.audio_buffer.clear()   # 立即释放缓冲，识别异步执行
                    print(f"说话结束，触发识别 ({len(buf)} bytes)")
                    self.ctx.tick("user_end", f"{self.wav_name}|{len(buf)}")
                    # 不阻塞本连接消息 worker：快照交给独立识别任务排队执行，
                    # 下一句（紧跟的 start/音频/end）可立即被处理与累积
                    asyncio.ensure_future(self._recognize_queued(buf))
                print("客户端结束说话")
        if "wav_name" in message:
            self.wav_name = message.get("wav_name", self.wav_name)
        if "language" in message:
            self.language = message.get("language", self.language)
        if "itn" in message:
            self.itn = bool(message.get("itn", self.itn))
        if "hotwords" in message:
            hw = message.get("hotwords", {})
            if isinstance(hw, str):
                try:
                    hw = json.loads(hw)
                except Exception:
                    hw = {}
            self.hotwords = hw if isinstance(hw, dict) else {}

    async def _rec_serial_lock(self):
        """按需创建会话识别锁（事件循环内首次使用时创建）"""
        if self._rec_lock is None:
            self._rec_lock = asyncio.Lock()
        return self._rec_lock

    async def _recognize_queued(self, buf: bytes):
        """识别队列任务：同连接多句按触发顺序串行执行，保证结果回传不乱序"""
        lock = await self._rec_serial_lock()
        async with lock:
            await self._recognize_final(buf)

    async def _recognize_final(self, buf: bytes):
        """整段识别：ASR → 声纹 → 结果回传（buf 为句音频快照）"""
        if not buf:
            return
        tmp_path = save_audio_to_wav(buf)
        try:
            res = await self._block(self.ctx.asr.generate, input=tmp_path,
                                    language=self.language, use_itn=self.itn,
                                    hotwords=self.hotwords, sem=self.ctx.sem_asr)
            if res and len(res) > 0:
                text = re.sub(r'<\|.*?\|>', '', res[0].get("text", ""))
                spk_name, spk_score = await self._block(self.sv.verify, buf, sem=self.ctx.sem_sv)
                msg = {"mode": "offline", "spk_name": spk_name, "spk_score": spk_score,
                       "text": text, "wav_name": self.wav_name, "is_final": True}
                await self.websocket.send(json.dumps(msg, ensure_ascii=False))
                print(f"识别结果: [{spk_name}] {text}")
                self.ctx.tick("sv_result_sent", f"{self.wav_name}|{spk_name}|{text}")
        except Exception as e:
            print(f"识别失败: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def _block(self, fn, *args, sem=None, **kwargs):
        """在线程池执行阻塞推理，受并发信号量约束"""
        loop = asyncio.get_running_loop()
        run = lambda: fn(*args, **kwargs)
        if sem is None:
            return await loop.run_in_executor(self.ctx.executor, run)
        async with sem:
            return await loop.run_in_executor(self.ctx.executor, run)
