# -*- coding: utf-8 -*-
# func/sensevoice/session.py
# 单个音频源的识别会话：独立连接 + 独立收发 + 独立 VAD/打断/声纹

import asyncio

from func.sensevoice.port import SenseVoicePort
from func.sensevoice.manager import SenseVoiceManager
from func.sensevoice.interrupt import InterruptDetector


class SenseVoiceSession:
    """封装一个音频源的完整识别链路（连接、采集、收发、VAD/打断）"""

    def __init__(self, source_id, config, log, hub, callback, tts_bridge,
                 allow_interrupt=True, speaker_verify=True, username="主人",
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

        self.port = SenseVoicePort(config, log)
        self.manager = SenseVoiceManager(
            config, self.port, log, callback,
            wav_name=self.wav_name,
            speaker_verify=self.speaker_verify,
            username=self.username,
        )
        self.interrupt = InterruptDetector(config, log)
        # 音频分块大小在 AudioConfig（hub.config），不在 SenseVoiceConfig
        self.silence_frame = b'\x00' * (hub.config.chunk * 2)

    async def run(self):
        """连接服务端，循环运行采集+接收，断线自动重连"""
        while self._is_running():
            capture = None
            recv = None
            try:
                async with self.port:
                    self.log.info(f"[{self.source_id}] 已连接 SenseVoice 服务器 (wav_name={self.wav_name})")
                    await self.manager.send_config()
                    capture = asyncio.create_task(self._capture_loop())
                    recv = asyncio.create_task(self.manager.receive_loop())
                    done, pending = await asyncio.wait(
                        [capture, recv],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
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

    async def _capture_loop(self):
        """采集循环：取源帧 → VAD/打断 → 发送音频与控制信号"""
        try:
            while self._is_running():
                frame = self.hub.next_frame(self.source_id)
                if frame is None:
                    frame = self.silence_frame

                # 项目内播放音频时，不检测电脑扬声器（转为静音帧）
                if self.source_id == 'loopback':
                    try:
                        from func.pipeline.audio_state import AudioState
                        if AudioState().is_playing():
                            frame = self.silence_frame
                    except Exception:
                        pass

                # 哼唱旁路：仅麦克风源参与哼唱检测
                if self.source_id == 'mic':
                    try:
                        from func.pipeline.toolbox_audio import ToolboxAudioBridge
                        ToolboxAudioBridge().dispatch_frame(frame)
                    except Exception:
                        pass

                # 每个源统一做 VAD（is_speaking）与打断检测（allow_interrupt 决定是否生效）
                vad_event = self.interrupt.update_vad(frame)
                interrupt_event = self.interrupt.update_interrupt(frame)

                if vad_event == 'started':
                    await self.manager.send_speaking(True)
                    self.manager.on_speech_start()
                elif vad_event == 'stopped':
                    await self.manager.send_speaking(False)
                    self.manager.on_speech_end()

                if interrupt_event and self.allow_interrupt:
                    self.tts_bridge.set_speaking(interrupt_event == 'started')

                await self.manager.send_audio(frame)
                await asyncio.sleep(self.hub.frame_duration)
        except Exception as e:
            self.log.error(f"[{self.source_id}] 采集循环异常: {e}", exc_info=True)
            raise
