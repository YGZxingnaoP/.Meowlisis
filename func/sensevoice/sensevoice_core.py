# -*- coding: utf-8 -*-
# func/sensevoice/sensevoice_core.py
# SenseVoice 语音识别编排入口

import asyncio
import threading
from typing import Optional, Callable

from func.log.default_log import DefaultLog
from func.sensevoice.config import SenseVoiceConfig
from func.sensevoice.port import SenseVoicePort
from func.sensevoice.microphone import Microphone
from func.sensevoice.audio import AudioProcessor
from func.sensevoice.interrupt import InterruptDetector
from func.sensevoice.manager import SenseVoiceManager
from func.pipeline.sensevoice_tts import SenseVoiceTtsBridge


class SenseVoiceCore:
    """SenseVoice 客户端核心，编排各子组件完成识别链路"""

    def __init__(self, callback: Optional[Callable[[str, str], None]] = None):
        self.log = DefaultLog().getLogger()
        self.config = SenseVoiceConfig()
        self.enabled = self.config.enabled

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        if not self.enabled:
            return

        self.callback = callback
        self.port = SenseVoicePort(self.config, self.log)
        self.microphone = Microphone(self.config, self.log)
        self.audio = AudioProcessor(self.config, self.log, self.microphone)
        self.interrupt = InterruptDetector(self.config, self.log)
        self.manager = SenseVoiceManager(self.config, self.port, self.log, callback)
        self.sensevoice_tts = SenseVoiceTtsBridge()

    def start(self):
        """启动识别后台线程"""
        if not self.enabled:
            self.log.info("SenseVoice 未启用")
            return
        if self.thread and self.thread.is_alive():
            self.log.warning("SenseVoice 已在运行")
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
        self.log.info("SenseVoice 识别线程已启动")

    def stop(self):
        """停止识别后台线程"""
        if not self.enabled:
            return
        self.running = False
        for task in self.manager.pending_tasks.values():
            task.cancel()
        self.manager.pending_tasks.clear()
        self.manager.pending_texts.clear()
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout=5)
        self.log.info("SenseVoice 识别线程已停止")

    def _run_async_loop(self):
        """运行异步事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except Exception as e:
            self.log.error(f"SenseVoice 主协程异常: {e}")
        finally:
            self.loop.close()

    async def _main(self):
        """主循环：连接服务端并并行运行采集与接收"""
        while self.running:
            try:
                async with self.port:
                    self.log.info(f"已连接到 SenseVoice 服务器 {self.config.server_url}")
                    await self.manager.send_config()
                    capture_task = asyncio.create_task(self._capture_loop())
                    recv_task = asyncio.create_task(self.manager.receive_loop())
                    done, pending = await asyncio.wait(
                        [capture_task, recv_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        task.cancel()
                    if self.running:
                        await asyncio.sleep(1)
            except Exception as e:
                if self.running:
                    self.log.error(f"SenseVoice 连接异常: {e}，1秒后重连")
                    await asyncio.sleep(1)
                else:
                    break

    async def _capture_loop(self):
        """采集循环：读取帧、检测说话状态、持续发送音频与控制信号"""
        self.microphone.open()
        try:
            while self.running:
                frame = self.audio.next_frame()

                # 音频旁路：分发到哼唱检测与落盘缓存（原 SenseVoice 链路不变）
                try:
                    from func.pipeline.toolbox_audio import ToolboxAudioBridge
                    ToolboxAudioBridge().dispatch_frame(frame)
                except Exception:
                    pass

                # 检测说话状态（VAD）与打断状态，分别上报/传递
                vad_event, interrupt_event = self.interrupt.update(frame)
                if vad_event:
                    await self.manager.send_speaking(vad_event == 'started')
                if interrupt_event:
                    self.sensevoice_tts.set_speaking(interrupt_event == 'started')

                # 持续发送音频帧，保持数据流连续不断
                await self.manager.send_audio(frame)
                await asyncio.sleep(self.audio.frame_duration)
        except Exception as e:
            self.log.error(f"音频采集循环异常: {e}", exc_info=True)
            raise
        finally:
            self.microphone.close()
            self.log.info("音频采集已停止")
