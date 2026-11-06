# -*- coding: utf-8 -*-
# func/sensevoice/session.py - 单源识别会话编排（连接/重连/采集/收发/检测）

import asyncio
import time

from func.sensevoice.port import SenseVoicePort
from func.sensevoice.manager import SenseVoiceManager
from func.sensevoice.interrupt import InterruptDetector


class SenseVoiceSession:
    """封装一个音频源的完整识别链路，断线自动重连"""

    # 连接类异常：识别服务未启动是常见状态，不该按 error 刷屏
    CONN_ERR_QUIET_SECONDS = 30.0

    def __init__(self, source_id, config, log, hub, callback, tts_bridge,
                 allow_interrupt=True, speaker_verify=True, username="主人",
                 llm_source="llm", subtitle_publish=False, subtitle=None,
                 is_running=None):
        self.source_id = source_id
        self.wav_name = source_id
        self.log = log
        self.hub = hub
        self.tts_bridge = tts_bridge
        self.allow_interrupt = bool(allow_interrupt)
        self.speaker_verify = bool(speaker_verify)
        self.username = username
        self._is_running = is_running or (lambda: True)
        self._last_conn_log = 0.0

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
        self.interrupt = InterruptDetector(config)
        self.silence_frame = b'\x00' * (hub.config.chunk * 2)

    def _apply_current_user(self):
        """按住说话：以最近注入的用户名刷新会话用户（缺省保持默认）"""
        name = self.hub.get_meta(self.source_id, 'username')
        if name:
            self.manager.username = name

    def _abort_answer(self):
        """用户开口：正在生成的回答立刻收手（不等它想完）"""
        try:
            from func.pipeline.sensevoice_llm import SenseVoiceLLMBridge
            SenseVoiceLLMBridge().abort_current()
        except Exception:
            self.log.exception("打断当前回答失败")

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
                self._log_session_error(e)
                await asyncio.sleep(1)
            finally:
                for t in (capture, recv):
                    if t is not None and not t.done():
                        t.cancel()

    @staticmethod
    def _is_conn_error(exc) -> bool:
        """是否为「连不上识别服务」这类异常（服务未启动时必然出现）"""
        if isinstance(exc, (OSError, ConnectionError, asyncio.TimeoutError)):
            return True
        try:
            import websockets
            return isinstance(exc, websockets.exceptions.WebSocketException)
        except Exception:
            return False

    def _log_session_error(self, exc):
        """会话异常日志：连接类降为 warning 并限流，避免识别服务未启动时刷屏"""
        if not self._is_conn_error(exc):
            self.log.error(f"[{self.source_id}] 会话异常: {exc}")
            return
        now = time.monotonic()
        if now - self._last_conn_log < self.CONN_ERR_QUIET_SECONDS:
            return
        self._last_conn_log = now
        self.log.warning(
            f"[{self.source_id}] 识别服务未就绪（{exc}），后台每秒重试，稍后自动连上"
        )

    def _after_reconnect(self):
        self._ptt_speaking = False
        self._dry_frames = 0
        self._suppress_until = 0.0
        # VAD 也必须复位：否则重连后 is_speaking 仍是 True，
        # 下一句不会触发 started，服务端会当成"还没开始说话"把音频丢掉
        self.interrupt.reset_speaking()
        self.hub.flush(self.source_id)
        # 采集缓冲已丢弃，哼唱检测器的半截缓冲也要一起丢，保证两边看的是同一段音频
        try:
            from func.pipeline.toolbox_audio import ToolboxAudioBridge
            ToolboxAudioBridge().reset_source(self.source_id)
        except Exception:
            pass
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
        """能量 VAD 模式（mic/loopback）：VAD 用最新帧保证实时，送 ASR 用完整序列保证不丢字"""
        # 取走当前已采集的全部帧：VAD 只看最新一帧，音频按序整段送给服务端
        frames = self.hub.pop_frames(self.source_id)
        latest = frames[-1] if frames else self.silence_frame

        if self.source_id == 'loopback':
            try:
                from func.pipeline.audio_state import AudioState
                if AudioState().is_playing():
                    latest = self.silence_frame
                    frames = []
            except Exception:
                pass

        # 哼唱旁路：每个音频源各自喂（检测器内部按源分状态），互不干扰
        try:
            from func.pipeline.toolbox_audio import ToolboxAudioBridge
            ToolboxAudioBridge().dispatch_frame(latest, self.source_id)
        except Exception:
            pass

        vad_event = self.interrupt.update_vad(latest)
        interrupt_event = self.interrupt.update_interrupt(latest)

        if vad_event == 'started':
            self.manager.send_speaking(True)
            self.manager.on_speech_start()
            self._abort_answer()
        elif vad_event == 'stopped':
            self.manager.send_speaking(False)
            self.manager.on_speech_end()

        if interrupt_event and self.allow_interrupt:
            self.tts_bridge.set_speaking(interrupt_event == 'started')

        if self.interrupt.is_speaking:
            if frames:
                for frame in frames:
                    self.manager.send_audio(frame)
            else:
                self.manager.send_audio(self.silence_frame)

    def _ptt_tick(self):
        """按住说话模式（inject）：能量 VAD 切句，ptt_end / 断流是硬边界

        - 有声 → 起句；段内静音达 silence_threshold → 收句（同一按住里可切多句）；
        - 收到 ptt_end（松手）→ 立即收句并清空在途残帧；
        - 断流（连续 2 拍没有帧）→ 兜底收句，防止客户端异常退出发不出 end。
        """
        self._apply_current_user()
        ev = self.hub.poll_event(self.source_id)
        if ev == 'ptt_end':
            if self._ptt_speaking:
                self._ptt_speaking = False
                self.manager.send_speaking(False)
                self.manager.on_speech_end()
            # 丢弃在途残帧，避免句尾残留被当成新句发送
            self.hub.flush(self.source_id)
            # VAD 状态也要复位，否则下一句开头不会触发 started
            self.interrupt.reset_speaking()
            self._dry_frames = 0
            self._suppress_until = time.monotonic() + 0.3

        frame = self.hub.next_frame(self.source_id)
        # 松手后的抑制期内丢掉残帧（不送 ASR、不喂哼唱检测）
        if frame is not None and time.monotonic() < self._suppress_until:
            frame = None
        latest = frame if frame is not None else self.silence_frame

        # 哼唱旁路：手机源同样送（按源分状态）
        try:
            from func.pipeline.toolbox_audio import ToolboxAudioBridge
            ToolboxAudioBridge().dispatch_frame(latest, self.source_id)
        except Exception:
            pass

        # 能量 VAD：有声起句、静音收句
        vad_event = self.interrupt.update_vad(latest)
        if vad_event == 'started':
            if not self._ptt_speaking:
                self._ptt_speaking = True
                self.manager.send_speaking(True)
                self.manager.on_speech_start()
                # 与原来一致：手机开口也打断正在生成的回答
                self._abort_answer()
        elif vad_event == 'stopped':
            if self._ptt_speaking:
                self._ptt_speaking = False
                self.manager.send_speaking(False)
                self.manager.on_speech_end()

        if frame is not None:
            self._dry_frames = 0
        elif self._ptt_speaking:
            self._dry_frames += 1
            if self._dry_frames >= 2:
                # 断流兜底：还没等到 ptt_end 就没帧了，按断流收句
                self._ptt_speaking = False
                self.manager.send_speaking(False)
                self.manager.on_speech_end()
                self.interrupt.reset_speaking()
                # 丢弃残留帧，下一句从干净缓冲开始
                self.hub.flush(self.source_id)

        if self._ptt_speaking and frame is not None:
            self.manager.send_audio(frame)
