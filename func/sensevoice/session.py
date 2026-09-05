# -*- coding: utf-8 -*-
# func/sensevoice/session.py - 单源识别会话编排（连接/重连/采集/收发/检测）

import asyncio
import time

from func.sensevoice.port import SenseVoicePort
from func.sensevoice.manager import SenseVoiceManager
from func.sensevoice.interrupt import InterruptDetector


class SenseVoiceSession:
    """封装一个音频源的完整识别链路，断线自动重连"""

    def __init__(self, source_id, config, log, hub, callback, tts_bridge,
                 allow_interrupt=True, speaker_verify=True, username="主人",
                 llm_source="llm", subtitle_publish=False, subtitle=None,
                 is_running=None):
        self.source_id = source_id
        self.wav_name = source_id
        self.config = config
        self.log = log
        self.hub = hub
        self.callback = callback
        self.tts_bridge = tts_bridge
        self.allow_interrupt = bool(allow_interrupt)
        self.speaker_verify = bool(speaker_verify)
        self.username = username
        self._is_running = is_running or (lambda: True)

        # inject 源为「按住说话」语义：边界由 end 事件/断流决定，不套用环境能量 VAD
        self.ptt_mode = (source_id == 'inject')
        self._ptt_speaking = False
        self._dry_frames = 0
        self._suppress_until = 0.0

        self.port = SenseVoicePort(config, log)
        self.manager = SenseVoiceManager(
            config, self.port, log, callback,
            wav_name=self.wav_name,
            speaker_verify=self.speaker_verify,
            username=self.username,
            llm_source=llm_source,
            subtitle_publish=subtitle_publish,
            subtitle=subtitle,
        )
        self.interrupt = InterruptDetector(config, log)
        self.silence_frame = b'\x00' * (hub.config.chunk * 2)

    def _apply_current_user(self):
        """按住说话：以最近注入的用户名刷新会话用户（缺省保持默认）"""
        name = self.hub.get_meta(self.source_id, 'username')
        if name:
            self.manager.username = name

    async def run(self):
        """连接后并行跑采集与接收，异常/拥塞自动重连"""
        while self._is_running():
            capture = None
            recv = None
            try:
                async with self.port:
                    self.log.info(f"[{self.source_id}] 已连接 SenseVoice 服务器 (wav_name={self.wav_name})")
                    await self.manager.send_config()
                    self._after_reconnect()
                    capture = asyncio.create_task(self._capture_loop())
                    recv = asyncio.create_task(self.manager.receive_loop())
                    done, pending = await asyncio.wait(
                        [capture, recv],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
                    for t in done:
                        if not t.cancelled() and t.exception() is not None:
                            self.log.error(f"[{self.source_id}] 会话任务异常: {t.exception()}")
                    if self._is_running():
                        await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not self._is_running():
                    break
                self.log.error(f"[{self.source_id}] 会话异常: {e}")
                await asyncio.sleep(1)
            finally:
                for t in (capture, recv):
                    if t is not None and not t.done():
                        t.cancel()

    def _after_reconnect(self):
        self._ptt_speaking = False
        self._dry_frames = 0
        self._suppress_until = 0.0
        self.hub.flush(self.source_id)
        self.manager.send_speaking(False)

    async def _capture_loop(self):
        """按源模式取帧处理；发送拥塞时抛错触发重连"""
        health_cnt = 0
        while self._is_running():
            t0 = time.monotonic()
            if self.ptt_mode:
                self._ptt_tick()
            else:
                self._vad_tick()
            health_cnt += 1
            if health_cnt >= 2:
                health_cnt = 0
                if not self.port.check_health():
                    raise ConnectionError("识别通道异常")
            wait = self.hub.frame_duration - (time.monotonic() - t0)
            if wait > 0:
                await asyncio.sleep(wait)

    def _vad_tick(self):
        """能量 VAD 模式（mic/loopback）：检测说话状态，说话中才发帧"""
        frame = self.hub.next_frame(self.source_id)
        if frame is None:
            frame = self.silence_frame

        if self.source_id == 'loopback':
            try:
                from func.pipeline.audio_state import AudioState
                if AudioState().is_playing():
                    frame = self.silence_frame
            except Exception:
                pass

        if self.source_id == 'mic':
            try:
                from func.pipeline.toolbox_audio import ToolboxAudioBridge
                ToolboxAudioBridge().dispatch_frame(frame)
            except Exception:
                pass

        vad_event = self.interrupt.update_vad(frame)
        interrupt_event = self.interrupt.update_interrupt(frame)

        if vad_event == 'started':
            self.manager.send_speaking(True)
            self.manager.on_speech_start()
        elif vad_event == 'stopped':
            self.manager.send_speaking(False)
            self.manager.on_speech_end()

        if interrupt_event and self.allow_interrupt:
            self.tts_bridge.set_speaking(interrupt_event == 'started')

        if self.interrupt.is_speaking:
            self.manager.send_audio(frame)

    def _ptt_tick(self):
        """按住说话模式（inject）：有注入帧即说话段，end 事件/断流立即判停"""
        self._apply_current_user()
        ev = self.hub.poll_event(self.source_id)
        if ev == 'ptt_end':
            if self._ptt_speaking:
                self._ptt_speaking = False
                self.manager.send_speaking(False)
                self.manager.on_speech_end()
            # 丢弃在途残帧，避免句尾残留被当成新句发送
            self.hub.flush(self.source_id)
            self._dry_frames = 0
            self._suppress_until = time.monotonic() + 0.3

        frame = self.hub.next_frame(self.source_id)
        if frame is not None:
            self._dry_frames = 0
            if time.monotonic() >= self._suppress_until:
                if not self._ptt_speaking:
                    self._ptt_speaking = True
                    self.manager.send_speaking(True)
                    self.manager.on_speech_start()
                self.manager.send_audio(frame)
        elif self._ptt_speaking:
            self._dry_frames += 1
            if self._dry_frames >= 2:
                self._ptt_speaking = False
                self.manager.send_speaking(False)
                self.manager.on_speech_end()
                # 断流判停：丢弃残留帧，下一句从干净缓冲开始
                self.hub.flush(self.source_id)
