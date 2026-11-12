# -*- coding: utf-8 -*-
# server/session.py - 单连接识别会话：说话状态/音频累积/整段识别

import asyncio
import json
import os
import re

import numpy as np

SAMPLE_RATE = 16000
# 首尾静音裁剪：10ms 一帧，RMS 低于该值视为静音，保留 100ms 余量
TRIM_RMS = 300.0
TRIM_HOP = 160
TRIM_MARGIN = 1600


def trim_silence(buf: bytes):
    """裁掉首尾静音并转 float32；返回 (float32 音频, 时长秒)"""
    a = np.frombuffer(buf, dtype=np.int16)
    if a.size == 0:
        return np.zeros(0, dtype=np.float32), 0.0
    n = a.size // TRIM_HOP
    if n <= 0:
        return a.astype(np.float32) / 32768.0, a.size / SAMPLE_RATE
    frames = a[:n * TRIM_HOP].reshape(n, TRIM_HOP).astype(np.float32)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    idx = np.where(rms >= TRIM_RMS)[0]
    if idx.size == 0:
        return a.astype(np.float32) / 32768.0, a.size / SAMPLE_RATE
    start = max(0, int(idx[0]) * TRIM_HOP - TRIM_MARGIN)
    end = min(a.size, (int(idx[-1]) + 1) * TRIM_HOP + TRIM_MARGIN)
    if end - start < int(SAMPLE_RATE * 0.3):
        start, end = 0, a.size
    cut = a[start:end]
    return cut.astype(np.float32) / 32768.0, cut.size / SAMPLE_RATE


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
        # 本句是否为哼唱（主程序在 is_speaking=false 时一并下发）
        self.hum = False
        # 声纹阈值（主程序按 config.yml 下发，缺省用命令行参数）
        self.sv_threshold = None
        self.sv_threshold_sing = None
        self._rec_lock = None  # 会话级识别串行锁：两句结果按序回传

    def handle_audio(self, audio_chunk: bytes):
        """说话中累积音频帧"""
        if self.is_speaking:
            self.audio_buffer.extend(audio_chunk)

    async def handle_text_message(self, message: dict):
        """处理文本消息：说话状态切换与识别参数更新"""
        # 本句属性与阈值：必须在 is_speaking=false 之前读，识别任务才能拿到本句快照
        if "hum" in message:
            self.hum = bool(message.get("hum"))
        if "sv_threshold" in message:
            self.sv_threshold = message.get("sv_threshold")
        if "sv_threshold_sing" in message:
            self.sv_threshold_sing = message.get("sv_threshold_sing")
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
                    print(f"说话结束，触发识别 ({len(buf)} bytes, hum={self.hum})")
                    self.ctx.tick("user_end", f"{self.wav_name}|{len(buf)}")
                    # 不阻塞本连接消息 worker：快照交给独立识别任务排队执行，
                    # 下一句（紧跟的 start/音频/end）可立即被处理与累积
                    asyncio.ensure_future(self._recognize_queued(
                        buf, self.hum, self.sv_threshold, self.sv_threshold_sing))
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

    async def _recognize_queued(self, buf: bytes, hum: bool = False,
                                thr_speech=None, thr_sing=None):
        """识别队列任务：同连接多句按触发顺序串行执行，保证结果回传不乱序"""
        lock = await self._rec_serial_lock()
        async with lock:
            await self._recognize_final(buf, hum, thr_speech, thr_sing)

    async def _recognize_final(self, buf: bytes, hum: bool = False,
                               thr_speech=None, thr_sing=None):
        """整段识别：裁首尾静音 → ASR 与声纹并行 → 结果回传"""
        if not buf:
            return
        try:
            audio, seconds = trim_silence(buf)
            if audio.size == 0:
                return
            # 两路并行：声纹 ~0.22s 藏到 ASR 后面，串行改并行约省 0.2s
            asr_coro = self._block(self.ctx.asr.generate, input=audio,
                                   language=self.language, use_itn=self.itn,
                                   hotwords=self.hotwords, sem=self.ctx.sem_asr)
            sv_coro = self._block(self.sv.verify, audio, hum=hum,
                                  thr_speech=thr_speech, thr_sing=thr_sing,
                                  sem=self.ctx.sem_sv)
            res, (spk_name, spk_score, spk_tpl) = await asyncio.gather(asr_coro, sv_coro)
            if res and len(res) > 0:
                text = re.sub(r'<\|.*?\|>', '', res[0].get("text", ""))
                msg = {"mode": "offline", "spk_name": spk_name, "spk_score": spk_score,
                       "spk_tpl": spk_tpl, "text": text, "wav_name": self.wav_name,
                       "is_final": True}
                await self.websocket.send(json.dumps(msg, ensure_ascii=False))
                print(f"识别结果: [{spk_name}:{spk_tpl or '-'}:{spk_score:.3f}] {text} ({seconds:.1f}s)")
                self.ctx.tick("sv_result_sent", f"{self.wav_name}|{spk_name}|{text}")
        except Exception as e:
            print(f"识别失败: {e}")

    async def _block(self, fn, *args, sem=None, **kwargs):
        """在线程池执行阻塞推理，受并发信号量约束"""
        loop = asyncio.get_running_loop()
        run = lambda: fn(*args, **kwargs)
        if sem is None:
            return await loop.run_in_executor(self.ctx.executor, run)
        async with sem:
            return await loop.run_in_executor(self.ctx.executor, run)
