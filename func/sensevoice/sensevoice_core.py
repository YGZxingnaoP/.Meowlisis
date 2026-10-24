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

    def _run_async_loop(self):
        """运行异步事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except Exception as e:
            # 停止时 loop.stop() 会让 run_until_complete 抛 "Event loop stopped"，
            if self.running:
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
        """主循环：按总开关与源开关动态创建/停止识别会话"""
        while self.running:
            self._sync_sessions()
            await asyncio.sleep(1)

    def __init__(self, callback: Optional[Callable[[str, str], None]] = None):
        self.log = DefaultLog().getLogger()
        self.config = SenseVoiceConfig()
        # 运行态总开关：由 apply_enabled 控制，与 config.sensevoice.enabled 解耦，便于热切换
        self.enabled = False

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # 无论是否启用都建好采集与会话骨架：热启用时才能直接开设备
        self.callback = callback
        self.hub = AudioHub()
        self.sensevoice_tts = SenseVoiceTtsBridge()
        self.subtitle = SenseVoiceSubtitle()  # 用户识别字幕（手机轮询显示）
        self.sessions = {}  # sid -> asyncio.Task

    def start(self):
        """启动识别后台线程（常驻），并按配置决定是否打开采集设备"""
        if self.thread and self.thread.is_alive():
            self.log.warning("SenseVoice 已在运行")
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
        if self.config.enabled:
            self.log.info("SenseVoice 识别后台线程已启动（高精度流式+声纹）")
        else:
            self.log.info("SenseVoice 后台线程已启动（未启用，等待热启用）")
        self.apply_enabled(self.config.enabled)

    def apply_enabled(self, on: bool):
        """热切换总开关：只开关采集设备与识别会话，线程常驻。

        - 关：先落 enabled=False（会话的 is_running 立刻为假，不会再把「服务未起」
              记成连接异常），再取消会话、关闭采集设备释放麦克风；
        - 开：按最新配置刷新分块节拍与各源开关，会话由 _sync_sessions 自动建立。
        """
        on = bool(on)
        if on == self.enabled:
            return
        self.enabled = on
        if on:
            self.hub.apply_config()
            self.log.info("🎤 SenseVoice 已热启用（按源开关建立识别会话）")
        else:
            self._cancel_sessions_threadsafe()
            self.hub.close()
            self.log.info("🔇 SenseVoice 已热停用（采集设备已释放）")

    def _cancel_sessions_threadsafe(self):
        """从其它线程安全地取消所有识别会话"""
        loop = self.loop
        if loop is None or not loop.is_running():
            return
        try:
            loop.call_soon_threadsafe(self._cancel_sessions)
        except Exception:
            pass

    def _cancel_sessions(self):
        for sid, task in list(self.sessions.items()):
            if task is not None and not task.done():
                task.cancel()
            self.sessions[sid] = None

    def set_source_enabled(self, sid, enabled):
        """运行时切换单个采集源；总开关关闭时只记录开关，不打开设备"""
        if self.enabled:
            self.hub.set_enabled(sid, enabled)
        else:
            self.hub.remember_enabled(sid, enabled)

    def stop(self):
        """停止识别后台线程"""
        if not self.running:
            return
        self.enabled = False
        self.running = False
        loop = self.loop
        # 先取消全部识别会话（会话的 is_running 已为假，会自己退出）
        if loop and loop.is_running():
            async def _shutdown():
                tasks = [t for t in self.sessions.values() if t is not None and not t.done()]
                for t in tasks:
                    t.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            try:
                asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=5)
            except Exception:
                pass
        self.hub.close()
        # 再停事件循环：放在协程外面，避免 "Event loop stopped before Future completed"
        if loop and loop.is_running():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=8)
        self.log.info("SenseVoice 识别线程已停止")


    def _sync_sessions(self):
        """同步会话：总开关关闭时全部取消；开启时按源开关创建/取消"""
        for sid in self.hub.source_ids():
            enabled = self.enabled and self.hub.is_enabled(sid)
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
            is_running=lambda: self.enabled and self.running and self.hub.is_enabled(sid),
        )
