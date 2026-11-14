# -*- coding: utf-8 -*-
# scripts/MossLive-test/mosslive/screen.py
# 屏幕实时采集：mss 抓屏 → 缩放 → JPEG → 交给 WebSocket 以 0x02 前缀发送。
# MOSS-Live 要求每帧一张 JPEG、一条二进制消息，不能是 Base64，也不能是 MP4/H.264。
# 采集参数以 media.configured.video 返回值为准（服务端可能调整），配置里的值只是请求值。

import io
import threading
import time
from pathlib import Path

from PIL import Image


class ScreenCapture:
    """屏幕推流线程"""

    def __init__(self, cfg_screen: dict, console, frames_dir: Path = None):
        self.console = console
        self.enabled = bool(cfg_screen.get("enabled"))
        self.monitor = int(cfg_screen.get("monitor") or 1)
        region = cfg_screen.get("region")
        self.region = dict(region) if isinstance(region, dict) else None
        self.interval_ms = int(cfg_screen.get("interval_ms") or 1000)
        self.max_long_side = int(cfg_screen.get("max_long_side") or 512)
        self.jpeg_quality = float(cfg_screen.get("jpeg_quality") or 0.75)
        self.save_frames = bool(cfg_screen.get("save_frames"))
        self.frames_dir = frames_dir
        self._on_frame = None
        self._loop = None
        self._thread = None
        self._stop = threading.Event()
        self._frame_id = 0

    # ---------- 配置 ----------

    def configure(self, video: dict):
        """按 media.configured.video 覆盖采集参数"""
        if not isinstance(video, dict):
            return
        if video.get("interval_ms"):
            self.interval_ms = max(200, int(video["interval_ms"]))
        if video.get("max_long_side"):
            self.max_long_side = max(128, int(video["max_long_side"]))
        if video.get("jpeg_quality") is not None:
            self.jpeg_quality = min(1.0, max(0.1, float(video["jpeg_quality"])))

    def describe(self) -> str:
        return (
            f"屏幕 {self.monitor}（{self.max_long_side}px 长边 / "
            f"质量 {self.jpeg_quality:.2f} / 每 {self.interval_ms}ms 一帧）"
        )

    # ---------- 生命周期 ----------

    def start(self, loop, on_frame):
        """loop：asyncio 事件循环；on_frame(bytes)：线程安全推送"""
        if not self.enabled or self._thread:
            return
        self._loop = loop
        self._on_frame = on_frame
        self._thread = threading.Thread(target=self._run, name="mosslive-screen", daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ---------- 采集 ----------

    def _run(self):
        try:
            import mss
        except Exception as e:
            self.console.error(f"mss 不可用，屏幕推流关闭: {e}")
            return
        try:
            sct = mss.MSS()
        except AttributeError:
            sct = mss.mss()

        region = self.region
        try:
            monitors = sct.monitors
            if region is None:
                idx = self.monitor if 0 <= self.monitor < len(monitors) else 1
                if idx >= len(monitors):
                    idx = 1 if len(monitors) > 1 else 0
                region = monitors[idx]
            if self.save_frames and self.frames_dir:
                self.frames_dir.mkdir(parents=True, exist_ok=True)
            self.console.info(f"屏幕推流开始: {self.describe()} region={region}")

            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    shot = sct.grab(region)
                except Exception as e:
                    self.console.warn(f"抓屏失败: {e}")
                    time.sleep(0.5)
                    continue
                try:
                    jpeg = self._encode(shot)
                except Exception as e:
                    self.console.warn(f"画面编码失败: {e}")
                    time.sleep(0.2)
                    continue
                if jpeg:
                    self._frame_id += 1
                    if self.save_frames and self.frames_dir and self._frame_id % 30 == 1:
                        try:
                            (self.frames_dir / f"frame_{self._frame_id:06d}.jpg").write_bytes(jpeg)
                        except Exception:
                            pass
                    try:
                        self._loop.call_soon_threadsafe(self._on_frame, b"\x02" + jpeg)
                    except RuntimeError:
                        break
                elapsed = time.monotonic() - started
                time.sleep(max(0.0, self.interval_ms / 1000.0 - elapsed))
        finally:
            try:
                sct.close()
            except Exception:
                pass
            self.console.info("屏幕推流已停止")

    def _encode(self, shot) -> bytes:
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        w, h = img.size
        long_side = max(w, h)
        if long_side > self.max_long_side:
            scale = self.max_long_side / float(long_side)
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=int(self.jpeg_quality * 100), optimize=False)
        return buf.getvalue()


def probe_screen(cfg_screen: dict, console) -> dict:
    """自检用：抓一帧，返回尺寸和 JPEG 大小（不发送）"""
    try:
        import mss
    except Exception as e:
        return {"ok": False, "error": f"mss 不可用: {e}"}
    try:
        try:
            sct = mss.MSS()
        except AttributeError:
            sct = mss.mss()
        monitors = sct.monitors
        region = cfg_screen.get("region")
        if not isinstance(region, dict):
            idx = int(cfg_screen.get("monitor") or 1)
            idx = idx if 0 <= idx < len(monitors) else 1
            region = monitors[idx]
        shot = sct.grab(region)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        long_side = int(cfg_screen.get("max_long_side") or 512)
        w, h = img.size
        if max(w, h) > long_side:
            scale = long_side / float(max(w, h))
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=int(float(cfg_screen.get("jpeg_quality") or 0.75) * 100))
        sct.close()
        return {"ok": True, "size": img.size, "jpeg_bytes": buf.tell()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
