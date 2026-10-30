# -*- coding: utf-8 -*-
"""截屏：按配置抓播放器窗口或整块屏幕，等比缩小后存成 JPEG。"""

import os

from PIL import ImageGrab

# 播放器进程名（窗口绑定确认用）
PLAYER_PROCESSES = (
    "vlc.exe", "potplayermini.exe", "potplayermini64.exe", "potplayer.exe",
    "mpc-hc.exe", "mpc-hc64.exe", "mpc-be.exe", "mpv.exe", "kmplayer.exe",
    "smplayer.exe", "wmplayer.exe", "tvnplayer.exe", "bilibili.exe",
    "qqvideo.exe", "qqlive.exe", "iqiyi.exe", "youku.exe", "mgtv.exe",
)

# 视频文件后缀（窗口标题里带这些多半是本地播放器）
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".rmvb", ".rm", ".flv", ".mov", ".wmv",
              ".ts", ".m2ts", ".webm", ".m4v", ".mpg", ".mpeg")

# 标题关键词（在线播放大多带站名/片名/集数）
PLAYER_KEYWORDS = (
    "播放器", "potplayer", "vlc", "mpc", "mpv", "kmplayer", "smplayer",
    "bilibili", "哔哩哔哩", "b站", "youtube", "netflix", "腾讯视频", "爱奇艺",
    "iqiyi", "优酷", "youku", "芒果", "mgtv", "西瓜视频", "抖音", "快手",
    "在线观看", "视频", "电影", "影视", "电视剧", "动漫", "动画", "番剧",
    "剧集", "影院", "movie", "film", "anime", "drama", "tv", "直播",
    "第", "集", "话", "p1", "p2", "正片", "预告",
)


class ScreenCapture:
    """一次观影期间共用一个实例：记住绑定到的窗口句柄，负责存活检测与截图。"""

    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.hwnd = 0
        self.title = ""
        self.process = ""

    # ==================== 窗口 ====================
    @staticmethod
    def list_windows(limit=200):
        """列出可见且有标题的顶层窗口：[{hwnd, title, process}]"""
        try:
            import win32gui
            import win32process
        except Exception:
            return []
        windows = []

        def _walk(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if title and title.strip():
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    windows.append({"hwnd": int(hwnd), "title": title.strip(),
                                    "process": ScreenCapture._process_name(pid)})
            except Exception:
                pass

        try:
            win32gui.EnumWindows(_walk, None)
        except Exception:
            return []
        return windows[:limit]

    @staticmethod
    def _process_name(pid):
        """按 PID 取进程名（psutil 缺失返回空串）"""
        try:
            import psutil
            return str(psutil.Process(int(pid)).name() or "").lower()
        except Exception:
            return ""

    @staticmethod
    def foreground_window():
        """当前前台窗口 {hwnd, title, process}；不可用返回 None"""
        try:
            import win32gui
            import win32process
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd or not win32gui.IsWindowVisible(hwnd):
                return None
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return {"hwnd": int(hwnd), "title": title,
                    "process": ScreenCapture._process_name(pid)}
        except Exception:
            return None

    def bind(self, title=""):
        """绑定窗口：先按标题包含匹配，找不到则取前台窗口；整屏模式不绑定。"""
        if self.config.mode != "window":
            return None
        title = str(title or self.config.window_title or "").strip()
        target = None
        if title:
            lowered = title.lower()
            for item in self.list_windows():
                if lowered in item["title"].lower():
                    target = item
                    break
        if target is None and not title:
            target = self.foreground_window()
        if target is None:
            self.log.warning(f"[movie_watch] 没找到播放器窗口（{title or '前台窗口'}）")
            return None
        self.hwnd = int(target["hwnd"])
        self.title = str(target["title"])
        self.process = str(target.get("process") or "")
        self.log.info(f"[movie_watch] 已绑定窗口：{self.title} "
                      f"({self.process or '未知进程'}, hwnd={self.hwnd})")
        return {"hwnd": self.hwnd, "title": self.title, "process": self.process}

    def is_video_window(self):
        """绑到的窗口像不像在放片（防误绑：记事本/文档/聊天窗口会被判 False）"""
        title = (self.title or "").lower()
        process = (self.process or "").lower()
        if process in PLAYER_PROCESSES:
            return True
        if any(title.endswith(ext) for ext in VIDEO_EXTS):
            return True
        if any(ext in title for ext in VIDEO_EXTS):
            return True
        return any(word in title for word in PLAYER_KEYWORDS)

    def is_alive(self):
        """绑定窗口是否还在（未绑定视为存活，交给整屏模式）"""
        if not self.hwnd:
            return True
        try:
            import win32gui
            return bool(win32gui.IsWindow(self.hwnd))
        except Exception:
            return True

    def window_bbox(self):
        """绑定窗口的屏幕坐标 (left, top, right, bottom)；取不到/已最小化返回 None"""
        if not self.hwnd:
            return None
        try:
            import win32gui
            if not win32gui.IsWindow(self.hwnd) or win32gui.IsIconic(self.hwnd):
                return None
            left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
        except Exception:
            return None
        if right - left < 64 or bottom - top < 64:
            return None
        return (int(left), int(top), int(right), int(bottom))

    # ==================== 截图 ====================
    def grab(self, out_path):
        """截一张并保存到 out_path（JPEG），返回 (ok, width, height)"""
        try:
            bbox = self.window_bbox() if self.config.mode == "window" else None
            if bbox:
                image = ImageGrab.grab(bbox=bbox)
            else:
                image = ImageGrab.grab(all_screens=bool(self.config.all_screens))
        except Exception:
            self.log.exception("[movie_watch] 截屏失败")
            return False, 0, 0

        try:
            side = int(self.config.max_side)
            if max(image.size) > side:
                image = image.copy()
                image.thumbnail((side, side))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            folder = os.path.dirname(os.path.abspath(out_path))
            if folder:
                os.makedirs(folder, exist_ok=True)
            image.save(out_path, "JPEG", quality=int(self.config.jpeg_quality), optimize=True)
            return True, image.size[0], image.size[1]
        except Exception:
            self.log.exception("[movie_watch] 截图保存失败")
            return False, 0, 0
