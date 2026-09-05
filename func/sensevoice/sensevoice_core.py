# -*- coding: utf-8 -*-
# func/sensevoice/sensevoice_core.py
# SenseVoice 语音识别编排入口（多源独立会话）

import asyncio
import threading
from typing import Optional, Callable

from func.log.default_log import DefaultLog
from func.audio import AudioHub
from func.sensevoice.config import SenseVoiceConfig
from func.sensevoice.session import SenseVoiceSession
from func.sensevoice.subtitle import SenseVoiceSubtitle
from func.pipeline.sensevoice_tts import SenseVoiceTtsBridge


class SenseVoiceCore:
    """SenseVoice 客户端核心：为每个启用的音频源创建独立识别会话"""

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
        self.hub = AudioHub()
        self.sensevoice_tts = SenseVoiceTtsBridge()
        self.subtitle = SenseVoiceSubtitle()  # 用户识别字幕（手机轮询显示）
        self.sessions = {}  # sid -> asyncio.Task

    def start(self):
        """启动识别后台线程"""
        if not self.enabled:
            self.log.info("SenseVoice 未启用")
            return
        if self.thread and self.thread.is_alive():
            self.log.warning("SenseVoice 已在运行")
            return
        self.running = True
        self.hub.open()
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
        self.log.info("SenseVoice 识别线程已启动")

    def stop(self):
        """停止识别后台线程"""
        if not self.enabled:
            return
        self.running = False
        self.hub.close()
        if self.loop and self.loop.is_running():
            async def _shutdown():
                tasks = [t for t in self.sessions.values() if t is not None and not t.done()]
                for t in tasks:
                    t.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                self.loop.stop()
            try:
                asyncio.run_coroutine_threadsafe(_shutdown(), self.loop)
            except Exception:
                self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout=8)
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
            # 取消并等待残留任务，避免 Event loop is closed / Task destroyed
            try:
                pending = asyncio.all_tasks(self.loop)
                for t in pending:
                    t.cancel()
                if pending:
                    self.loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            self.loop.close()

    async def _main(self):
        """主循环：按源开关动态创建/停止识别会话"""
        while self.running:
            self._sync_sessions()
            await asyncio.sleep(1)

    def _sync_sessions(self):
        """同步会话：启用的源创建会话任务，停用的源取消任务"""
        for sid in self.hub.source_ids():
            enabled = self.hub.is_enabled(sid)
            task = self.sessions.get(sid)
            if enabled and (task is None or task.done()):
                session = self._make_session(sid)
                self.sessions[sid] = asyncio.create_task(session.run())
                self.log.info(f"[{sid}] 识别会话已启动")
            elif not enabled and task is not None and not task.done():
                task.cancel()
                self.sessions[sid] = None
                self.log.info(f"[{sid}] 识别会话已停止")

    def _make_session(self, sid):
        scfg = self.hub.config.source_config(sid)
        # inject 源 = 手机语音通道：消息标记 source=phone、识别文本投用户字幕
        is_phone = (sid == 'inject')
        return SenseVoiceSession(
            source_id=sid,
            config=self.config,
            log=self.log,
            hub=self.hub,
            callback=self.callback,
            tts_bridge=self.sensevoice_tts,
            allow_interrupt=scfg.get('allow_interrupt', True),
            speaker_verify=scfg.get('speaker_verify', True),
            username=scfg.get('username', '手机用户'),
            llm_source='phone' if is_phone else 'llm',
            subtitle_publish=is_phone,
            subtitle=self.subtitle,
            is_running=lambda: self.running and self.hub.is_enabled(sid),
        )
