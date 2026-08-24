# -*- coding: utf-8 -*-
# func/vts/vts_window.py
# VTS 置顶透明窗口：捕获 VTS 画面 → 绿幕抠像 → 置顶显示（可调大小）

import threading
import time

import numpy as np

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.vts.config import VtsConfig


def _hex_to_rgb(color: str):
    """把 '#00FF00' 转成 (r, g, b)"""
    color = str(color or "#00FF00").strip().lstrip("#")
    if len(color) != 6:
        return (0, 255, 0)
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _numpy_to_ppm(img) -> bytes:
    """把 numpy RGB 图像（H x W x 3 uint8）转成 PPM 字节，供 tkinter.PhotoImage 直接读取"""
    h, w = img.shape[:2]
    header = f"P6\n{w} {h}\n255\n".encode("ascii")
    return header + np.ascontiguousarray(img[:, :, :3]).astype("uint8").tobytes()


@singleton
class VtsWindow:
    """VTS 画面置顶透明窗口（绿幕抠像）

    - 后台线程运行 tkinter mainloop；
    - 捕获 VTS 窗口画面（优先 pywin32，回退 mss，均不可用则降级为空）；
    - 把接近绿幕色的像素统一替换为精确绿色，配合窗口 -transparentcolor 实现透明；
    - 窗口大小/位置/置顶/绿幕颜色/容差均由 config 的 emote.window 节点控制。
    """

    # 默认 VTS 窗口标题关键词（用于 pywin32 查找窗口）
    DEFAULT_WINDOW_TITLE = "VTube Studio"

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = VtsConfig()
        self._thread = None
        self._running = False
        self._root = None

    def start(self):
        """启动置顶窗口（后台线程）"""
        if not self.config.window_enabled:
            self.log.info("VTS 置顶窗口未启用")
            return
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """停止置顶窗口"""
        if not self._running:
            return
        self._running = False
        try:
            if self._root is not None:
                self._root.after(0, self._root.destroy)
        except Exception:
            pass

    # ==================== 截图源 ====================
    def _grab_vts(self):
        """捕获画面，返回 (numpy RGB 图像 或 None)

        优先窗口采集（PrintWindow 能抓最小化/被遮挡窗口，最接近 OBS 游戏源）；
        失败再回退屏幕采集（mss，像 OBS 显示器采集）。
        """
        try:
            img = self._grab_win32()
            if img is not None and img.size > 0:
                return img
        except Exception:
            pass
        try:
            return self._grab_mss()
        except Exception:
            pass
        return None

    def _grab_win32(self):
        """pywin32：按窗口标题查找 VTS 窗口并 PrintWindow 截图（回退方案）"""
        import win32gui
        import win32ui
        import win32con

        hwnd = None
        title_kw = getattr(self.config, "window_title", None) or self.DEFAULT_WINDOW_TITLE

        def _enum(h, _):
            nonlocal hwnd
            if win32gui.IsWindowVisible(h) and title_kw.lower() in (win32gui.GetWindowText(h) or "").lower():
                hwnd = h

        win32gui.EnumWindows(_enum, None)
        if hwnd is None:
            raise RuntimeError("未找到 VTS 窗口")

        # 尺寸：最小化时 GetWindowRect 会返回 -32000，改用 GetWindowPlacement 的正常矩形
        w = h = 0
        try:
            placement = win32gui.GetWindowPlacement(hwnd)
            normal_rect = placement[4] if len(placement) > 4 else None
            if normal_rect:
                w = normal_rect[2] - normal_rect[0]
                h = normal_rect[3] - normal_rect[1]
        except Exception:
            pass
        if w <= 0 or h <= 0:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            w = right - left
            h = bottom - top
        if w <= 0 or h <= 0:
            raise RuntimeError("VTS 窗口尺寸无效")

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)

        # 优先 PrintWindow（支持 DWM 合成下的硬件加速窗口，避免截到黑屏）
        try:
            rendered = win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)  # 2 = PW_RENDERFULLCONTENT
        except Exception:
            rendered = 0
        if not rendered:
            # 回退 BitBlt（PrintWindow 对部分窗口可能返回 0）
            save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY)

        bmp_info = bmp.GetInfo()
        bmp_bits = bmp.GetBitmapBits(True)
        img = np.frombuffer(bmp_bits, dtype=np.uint8).reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
        # BGRA → RGB
        rgb = img[:, :, :3][:, :, ::-1].copy()

        win32gui.DeleteObject(bmp.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return rgb

    def _grab_mss(self):
        """mss：按配置抓取指定显示器（像 OBS 显示器采集）"""
        import mss
        with mss.mss() as sct:
            idx = int(getattr(self.config, "window_monitor", 1) or 1)
            if idx < 0 or idx >= len(sct.monitors):
                idx = 1 if len(sct.monitors) > 1 else 0
            monitor = sct.monitors[idx]
            shot = sct.grab(monitor)
            img = np.array(shot)[:, :, :3]
            return np.ascontiguousarray(img[:, :, ::-1])  # BGRA → RGB

    # ==================== 抠像与显示 ====================
    def _key_out(self, img):
        """把接近绿幕色的像素替换为精确绿色（配合 transparentcolor）"""
        target = np.array(_hex_to_rgb(self.config.window_green), dtype=np.float64)
        tol = float(self.config.window_tolerance)
        arr = img.astype(np.float64)
        dist = np.sqrt(np.sum((arr - target) ** 2, axis=2))
        mask = dist < tol
        out = img.copy()
        out[mask] = _hex_to_rgb(self.config.window_green)
        return out

    def _run(self):
        try:
            import tkinter as tk
        except Exception as e:
            self.log.error(f"tkinter 不可用，VTS 置顶窗口启动失败: {e}")
            self._running = False
            return

        cfg = self.config
        root = tk.Tk()
        self._root = root
        root.title("VTS Pet")
        root.geometry(f"{cfg.window_width}x{cfg.window_height}+{cfg.window_x}+{cfg.window_y}")
        root.overrideredirect(True)  # 无边框
        root.wm_attributes("-topmost", cfg.window_always_on_top)
        try:
            root.wm_attributes("-transparentcolor", cfg.window_green)
        except Exception as e:
            self.log.warning(f"设置透明色失败（可能不支持）: {e}")

        label = tk.Label(root, bg=cfg.window_green, bd=0)
        label.pack(fill="both", expand=True)

        photo = None

        def tick():
            if not self._running:
                try:
                    root.destroy()
                except Exception:
                    pass
                return
            nonlocal photo
            try:
                img = self._grab_vts()
                if img is not None:
                    img = self._key_out(img)
                    # 缩放到窗口尺寸
                    try:
                        from PIL import Image
                        pil = Image.fromarray(img)
                        pil = pil.resize((cfg.window_width, cfg.window_height))
                        img = np.array(pil)
                    except Exception:
                        # 无 PIL 时直接裁剪/拉伸：仅简单 resize 不可用则原图
                        pass
                    photo = tk.PhotoImage(data=_numpy_to_ppm(img))
                    label.config(image=photo)
            except Exception as e:
                self.log.debug(f"VTS 窗口刷新失败: {e}")
            interval_ms = max(1, int(1000 / max(1, cfg.window_fps)))
            root.after(interval_ms, tick)

        root.after(0, tick)
        try:
            root.mainloop()
        finally:
            self._running = False
            self._root = None
