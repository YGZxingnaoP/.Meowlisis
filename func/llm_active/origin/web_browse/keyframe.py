# -*- coding: utf-8 -*-
# func/llm_active/origin/web_browse/keyframe.py
# ffmpeg 流式抽帧：视频 n 等分，每段随机抽 1 帧，压缩到 720p

import os
import random
import subprocess
import sys
import uuid
from typing import List, Optional

from func.log.default_log import DefaultLog
from func.llm_active.origin.web_browse.config import AutoWebBrowseConfig

# B站视频流防盗链：ffmpeg 需携带 Referer 与 UA 才能访问
_BILI_HEADERS = (
    "Referer: https://www.bilibili.com/\r\n"
    "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class AutoKeyframe:
    """流式抽帧：直接对视频流 url 用 ffmpeg 抽帧，不下载整段视频"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = AutoWebBrowseConfig()

    def extract(self, stream_url: str, duration_sec: int, n: int = 5) -> List[str]:
        """按 n 等分、每段随机抽 1 帧，压缩到 720p，返回帧路径列表（失败返回空）"""
        ffmpeg = self._ffmpeg_path()
        if not ffmpeg:
            self.log.error("[WebBrowse] 未找到 ffmpeg，无法抽帧")
            return []
        if not stream_url:
            return []
        duration_sec = max(0, int(duration_sec or 0))
        n = max(1, int(n))
        if duration_sec <= 0:
            return []

        os.makedirs(self.config.frame_tmp_dir, exist_ok=True)
        timestamps = self._pick_timestamps(duration_sec, n)

        paths: List[str] = []
        for t in timestamps:
            path = os.path.join(
                self.config.frame_tmp_dir,
                f"frame_{int(t)}_{uuid.uuid4().hex[:6]}.jpg",
            )
            if self._grab_one(ffmpeg, stream_url, t, path):
                paths.append(path)
        return paths

    def cleanup(self, paths: List[str]):
        """删除临时帧文件（帧用后即删）"""
        for p in paths or []:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                self.log.exception(f"[WebBrowse] 删除帧失败: {p}")

    @staticmethod
    def _pick_timestamps(duration_sec: int, n: int) -> List[int]:
        """n 等分，每段内随机取一个时间点"""
        segment = duration_sec / n
        timestamps = []
        for i in range(n):
            start = i * segment
            end = min((i + 1) * segment, duration_sec - 0.5)
            if end <= start:
                end = start + 0.5
            timestamps.append(int(random.uniform(start, end)))
        return timestamps

    def _grab_one(self, ffmpeg: str, url: str, t: int, out_path: str) -> bool:
        """ffmpeg 单帧流式抽帧，缩放到 720p"""
        cmd = [
            ffmpeg,
            "-y",
            "-ss", str(t),
            "-headers", _BILI_HEADERS,
            "-i", url,
            "-frames:v", "1",
            "-vf", "scale=-2:720",
            out_path,
        ]
        try:
            r = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return True
            return False
        except Exception:
            self.log.exception(f"[WebBrowse] ffmpeg 抽帧异常 t={t}")
            return False

    @staticmethod
    def _ffmpeg_path() -> Optional[str]:
        """定位 runtime/Scripts/ffmpeg.exe（独立环境，不依赖系统 PATH）"""
        exe_dir = os.path.dirname(sys.executable)
        for candidate in (
            os.path.join(exe_dir, "Scripts", "ffmpeg.exe"),
            os.path.join(exe_dir, "ffmpeg.exe"),
        ):
            if os.path.exists(candidate):
                return candidate
        return None
