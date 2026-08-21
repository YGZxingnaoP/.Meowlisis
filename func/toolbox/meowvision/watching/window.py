# -*- coding: utf-8 -*-
# func/toolbox/meowvision/watching/window.py
# 窗口枚举：获取当前可见的顶层窗口列表（标题 + 进程名 + 句柄），供 AI 决定绑定窗口

from typing import List, Dict, Optional

from func.log.default_log import DefaultLog


class TBWindowList:
    """窗口枚举器：列出当前可见的顶层窗口，供 watching 绑定游戏窗口。

    - 仅返回有标题、可见、有边框的窗口（过滤系统托盘/工具窗口）；
    - 进程名优先用 psutil，缺失则降级仅返回 PID；
    - 窗口不存在/环境不支持时优雅返回空列表。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._psutil = self._try_import_psutil()

    @staticmethod
    def _try_import_psutil():
        try:
            import psutil
            return psutil
        except Exception:
            return None

    def list_windows(self, limit: int = 50) -> List[Dict]:
        """返回可见窗口列表：[{hwnd, title, pid, process}]，按标题过滤空窗口"""
        windows: List[Dict] = []
        try:
            import win32gui
            import win32process
        except Exception as e:
            self.log.warning(f"[Watching] 窗口枚举不可用: {e}")
            return windows

        def _callback(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if not title or not title.strip():
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process = self._process_name(pid)
                windows.append({
                    "hwnd": int(hwnd),
                    "title": title.strip(),
                    "pid": int(pid or 0),
                    "process": process,
                })
            except Exception:
                pass

        try:
            win32gui.EnumWindows(_callback, None)
        except Exception as e:
            self.log.warning(f"[Watching] 枚举窗口失败: {e}")

        # 去重（同一标题进程可多个，保留 hwnd 不同即可）
        return windows[:limit]

    def _process_name(self, pid: int) -> str:
        """按 PID 获取进程名；psutil 缺失返回空串"""
        if not pid:
            return ""
        if self._psutil:
            try:
                return self._psutil.Process(pid).name() or ""
            except Exception:
                return ""
        return ""

    def find_hwnd(self, title: str) -> Optional[int]:
        """按窗口标题精确/包含匹配，返回第一个命中的 hwnd；找不到返回 None"""
        title = (title or "").strip()
        if not title:
            return None
        for w in self.list_windows(limit=200):
            wt = w.get("title", "")
            if wt == title or title in wt:
                return w.get("hwnd")
        return None

    def is_window_alive(self, hwnd: int) -> bool:
        """判断窗口句柄是否仍然存在"""
        if not hwnd:
            return False
        try:
            import win32gui
            return bool(win32gui.IsWindow(int(hwnd)))
        except Exception:
            return False
