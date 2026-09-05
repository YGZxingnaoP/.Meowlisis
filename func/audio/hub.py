# -*- coding: utf-8 -*-
# func/audio/hub.py
# 多源音频采集管理器：各源独立开关、独立采集线程、分源输出（不混音）

import threading
import time
from collections import deque

from func.audio.config import AudioConfig
from func.audio.sources import MicrophoneSource, LoopbackSource, InjectSource


class AudioHub:
    """管理多个音频采集源，每个源独立缓冲、独立输出，供各识别会话独立取帧"""

    def __init__(self, config=None, log=None):
        if config is None:
            config = AudioConfig()
        if log is None:
            from func.log.default_log import DefaultLog
            log = DefaultLog().getLogger()

        self.config = config
        self.log = log
        self.frame_duration = config.chunk_size_ms / 1000.0

        self._lock = threading.RLock()
        self._sources = {}   # id -> AudioSource 实例
        self._enabled = {}   # id -> bool
        self._buffers = {}   # id -> deque
        self._events = {}    # id -> 事件队列（如 PTT 结束信号）
        self._meta = {}      # id -> 会话元数据（如当前手机用户）
        self._threads = {}   # id -> Thread
        self._running = {}   # id -> bool

        self._setup()

    def _setup(self):
        for sid, scfg in self.config.sources.items():
            stype = scfg.get('type', 'mic')
            device_index = scfg.get('device_index', -1)
            if stype == 'loopback':
                source = LoopbackSource(self.config, self.log, device_index=device_index)
            elif stype == 'inject':
                source = InjectSource(self.config, self.log)
            else:
                source = MicrophoneSource(self.config, self.log, device_index=device_index)
            self._sources[sid] = source
            self._enabled[sid] = bool(scfg.get('enabled', False))
            self._buffers[sid] = deque(maxlen=64)
            self._events[sid] = deque(maxlen=8)
            self._threads[sid] = None
            self._running[sid] = False

    # ---------- 源开关 ----------
    def source_ids(self):
        return list(self._sources.keys())

    def source_status(self):
        with self._lock:
            return {sid: self._enabled[sid] for sid in self._sources}

    def is_enabled(self, sid):
        with self._lock:
            return self._enabled.get(sid, False)

    def set_enabled(self, sid, enabled):
        enabled = bool(enabled)
        with self._lock:
            if sid not in self._sources:
                return
            if self._enabled[sid] == enabled:
                return
            self._enabled[sid] = enabled
        if enabled:
            self._start_source(sid)
        else:
            self._stop_source(sid)

    # ---------- 注入接口 ----------
    def inject(self, sid, data: bytes):
        """向指定源灌入外部音频（仅 inject 源支持）"""
        source = self._sources.get(sid)
        if source is not None and hasattr(source, 'inject'):
            source.inject(data)

    def notify(self, sid, event: str):
        """向指定源投递事件（如 'ptt_end'），由会话轮询消费"""
        with self._lock:
            dq = self._events.get(sid)
            if dq is not None:
                dq.append(event)

    def set_meta(self, sid, key: str, value):
        """写入指定源会话元数据（如当前手机用户），供会话读取"""
        with self._lock:
            self._meta.setdefault(sid, {})[key] = value

    def get_meta(self, sid, key: str, default=None):
        """读取指定源会话元数据"""
        with self._lock:
            return self._meta.get(sid, {}).get(key, default)

    def poll_event(self, sid):
        """取指定源一个事件；无则返回 None"""
        with self._lock:
            dq = self._events.get(sid)
            return dq.popleft() if dq else None

    def flush(self, sid):
        """清空指定源缓冲与源内未消费数据（丢弃在途残块）"""
        with self._lock:
            buf = self._buffers.get(sid)
            if buf:
                buf.clear()
        source = self._sources.get(sid)
        if source is not None and hasattr(source, 'clear'):
            source.clear()

    # ---------- 生命周期 ----------
    def open(self):
        for sid in list(self._sources.keys()):
            if self._enabled[sid]:
                self._start_source(sid)

    def close(self):
        for sid in list(self._sources.keys()):
            self._stop_source(sid)

    # ---------- 分源输出 ----------
    def next_frame(self, sid):
        """取指定源一帧；缓冲空时返回 None（由会话补静音占位，用于区分断流）"""
        with self._lock:
            buf = self._buffers.get(sid)
            if buf:
                try:
                    return buf.popleft()
                except IndexError:
                    pass
        return None

    # ---------- 内部采集线程 ----------
    def _start_source(self, sid):
        with self._lock:
            if self._running[sid]:
                return
            self._running[sid] = True
            source = self._sources[sid]
            t = threading.Thread(
                target=self._capture_loop, args=(sid, source),
                daemon=True, name=f"audio-{sid}"
            )
            self._threads[sid] = t
            t.start()

    def _stop_source(self, sid):
        with self._lock:
            self._running[sid] = False
        t = self._threads.get(sid)
        if t and t.is_alive():
            t.join(timeout=1)
        source = self._sources.get(sid)
        if source:
            try:
                source.close()
            except Exception:
                pass
        with self._lock:
            buf = self._buffers.get(sid)
            if buf:
                buf.clear()

    def _capture_loop(self, sid, source):
        try:
            source.open()
        except Exception as e:
            self.log.error(f"音频源 {sid} 打开失败: {e}")
            with self._lock:
                self._running[sid] = False
                self._enabled[sid] = False
            return

        buf = self._buffers[sid]
        limit = buf.maxlen
        try:
            while self._running[sid]:
                frame = source.read()
                if frame is not None:
                    while self._running[sid]:
                        with self._lock:
                            if limit is None or len(buf) < limit:
                                buf.append(frame)
                                break
                        time.sleep(0.01)
                else:
                    # 队列类源（inject）无数据时短暂休眠，避免忙等
                    time.sleep(0.01)
        except Exception as e:
            self.log.error(f"音频源 {sid} 采集异常: {e}")
        finally:
            try:
                source.close()
            except Exception:
                pass
            with self._lock:
                self._running[sid] = False

    @staticmethod
    def list_devices():
        """枚举麦克风 + 扬声器回环设备"""
        devices = MicrophoneSource.list_devices()
        devices.extend(LoopbackSource.list_devices())
        return devices
