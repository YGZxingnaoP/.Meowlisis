# -*- coding: utf-8 -*-
# func/toolbox/svg_painter/render.py
# SVG → PNG 渲染器（用本机 Edge headless 截图，渲染透明底为白底）
# 供 QQ 画完发图使用；找不到 Edge / 渲染失败时返回 None（调用方降级处理，不抛错）

import base64
import os
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime

from func.log.default_log import DefaultLog


class TBSvgPainterRender:
    """Edge headless 渲染：把 SVG 文本渲染成 PNG（QQ 图片发送用）"""

    EDGE_CANDIDATES = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"{local}\Microsoft\Edge\Application\msedge.exe",
    ]

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._lock = threading.Lock()
        self._edge = None

    # ==================== Edge 探测 ====================
    def find_edge(self) -> str:
        if self._edge:
            return self._edge
        local = os.environ.get("LOCALAPPDATA", "")
        for cand in self.EDGE_CANDIDATES:
            path = cand.format(local=local) if "{local}" in cand else cand
            if path and os.path.exists(path):
                self._edge = path
                return path
        edge = shutil.which("msedge")
        if edge:
            self._edge = edge
            return edge
        return ""

    # ==================== 渲染 ====================
    def svg_to_png(self, svg_text: str, out_dir: str = None, scale: int = 2) -> str:
        """把完整 svg 文本渲染成 png（透明底转白底），成功返回 png 绝对路径，失败返回空串"""
        svg_text = (svg_text or "").strip()
        if not svg_text:
            return ""
        m_w = re.search(r'\bwidth\s*=\s*["\'](\d+(?:\.\d+)?)["\']', svg_text)
        m_h = re.search(r'\bheight\s*=\s*["\'](\d+(?:\.\d+)?)["\']', svg_text)
        try:
            width = int(float(m_w.group(1))) if m_w else 600
            height = int(float(m_h.group(1))) if m_h else 800
        except Exception:
            width, height = 600, 800
        width = max(64, min(width, 4096))
        height = max(64, min(height, 8192))
        scale = max(1, min(int(scale or 2), 4))

        edge = self.find_edge()
        if not edge:
            self.log.warning("[svg_painter] 未找到 Edge，无法渲染画作 PNG（QQ 发图跳过）")
            return ""
        try:
            os.makedirs(out_dir, exist_ok=True) if out_dir else None
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3]
            out_png = os.path.join(out_dir or tempfile.gettempdir(), f"svg_render_{stamp}.png")
            b64 = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")
            html = (
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                "<style>html,body{margin:0;padding:0;overflow:hidden;background:#ffffff;}"
                f"img{{width:{width}px;height:{height}px;display:block;}}</style></head>"
                f"<body><img src=\"data:image/svg+xml;base64,{b64}\"></body></html>"
            )
            tmp_html = os.path.join(tempfile.gettempdir(), f"svg_render_{stamp}.html")
            with open(tmp_html, "w", encoding="utf-8") as f:
                f.write(html)
            cmd = [
                edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--no-first-run", "--disable-extensions", "--mute-audio",
                f"--force-device-scale-factor={scale}",
                f"--window-size={width},{height}",
                f"--screenshot={out_png}", tmp_html,
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
            try:
                os.remove(tmp_html)
            except Exception:
                pass
            if proc.returncode == 0 and os.path.exists(out_png) and os.path.getsize(out_png) > 0:
                self.log.info(f"[svg_painter] 画作已渲染 PNG: {out_png}")
                return out_png
            # 老版 Edge 参数回退
            if "--headless=new" in cmd:
                cmd[cmd.index("--headless=new")] = "--headless"
                proc = subprocess.run(cmd, capture_output=True, timeout=30)
                if proc.returncode == 0 and os.path.exists(out_png) and os.path.getsize(out_png) > 0:
                    self.log.info(f"[svg_painter] 画作已渲染 PNG(legacy): {out_png}")
                    return out_png
            self.log.warning(f"[svg_painter] Edge 渲染失败 rc={proc.returncode}")
            try:
                if os.path.exists(out_png):
                    os.remove(out_png)
            except Exception:
                pass
            return ""
        except Exception:
            self.log.exception("[svg_painter] SVG 渲染异常")
            return ""


_svg_renderer = None


def get_svg_renderer():
    """全局渲染器单例"""
    global _svg_renderer
    if _svg_renderer is None:
        _svg_renderer = TBSvgPainterRender()
    return _svg_renderer
