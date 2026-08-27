# -*- coding: utf-8 -*-
# func/meowsinger/netease/netease_music.py
# 从网易云服务获取歌曲与歌词，清洗歌词并保存到 raw_list
import os
import re
import shutil

import requests

from func.log.default_log import DefaultLog
from func.meowsinger.config import MeowSingerConfig

RAW_DIR = os.path.join("character", "songs", "raw_list")

META_KEYWORDS = [
    "作词", "作曲", "编曲", "制作人", "制作公司", "录音", "混音", "和声",
    "监制", "吉他", "贝斯", "鼓", "键盘", "弦乐", "录音室", "男声", "女声",
    "戏腔", "演唱", "发行", "出品", "母带", "编曲人", "制作", "歌手",
]

TIME_RE = re.compile(r"\[(\d{1,2}):(\d{2})\.(\d{1,3})\]")


class MeowNeteaseMusic:
    """网易云歌曲获取：搜索下载、歌词清洗、落盘 raw_list"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowSingerConfig()

    def search_and_download(self, title, artist=None):
        """调网易云服务搜索并下载，返回歌曲信息 dict 或 None"""
        try:
            payload = {"songname": title}
            if artist:
                payload["artist"] = artist
            resp = requests.post(
                f"{self.config.netease_url}/api/sing",
                json=payload,
                timeout=60,
            )
            data = resp.json()
            if data.get("code") != 200:
                self.log.warning(f"[Netease] 点歌失败: {data.get('msg')}")
                return None
            return {
                "song_id": data.get("song_id"),
                "songname": data.get("songname", title),
                "artist": data.get("artist", ""),
                "artists": data.get("artists", []),
                "local_path": data.get("local_path", ""),
                "duration": data.get("duration", 0),
            }
        except Exception:
            self.log.exception("[Netease] 搜索下载异常")
            return None

    def fetch_lyric(self, song_id):
        """调网易云服务获取歌词，返回原始 lrc 字符串"""
        try:
            resp = requests.get(f"{self.config.netease_url}/api/lyric",
                                params={"song_id": song_id}, timeout=30)
            data = resp.json()
            if data.get("code") != 200:
                return ""
            return data.get("lrc", "")
        except Exception:
            self.log.exception("[Netease] 获取歌词异常")
            return ""

    def save_song(self, title, info):
        """把下载的歌曲与清洗后的歌词保存到 raw_list/歌名/，返回本地 mp3 路径"""
        if not info or not info.get("local_path"):
            return ""
        folder = os.path.join(RAW_DIR, self._safe_name(title))
        os.makedirs(folder, exist_ok=True)

        mp3_path = os.path.join(folder, f"{self._safe_name(title)}.mp3")
        try:
            if os.path.abspath(info["local_path"]) != os.path.abspath(mp3_path):
                shutil.copy(info["local_path"], mp3_path)
        except Exception:
            self.log.exception("[Netease] 复制 mp3 失败")
            return info["local_path"]

        lrc = self.fetch_lyric(info.get("song_id"))
        cleaned = self.clean_lrc(lrc)
        if cleaned:
            with open(os.path.join(folder, f"{self._safe_name(title)}.lrc"),
                      "w", encoding="utf-8") as f:
                f.write(cleaned)
        return mp3_path

    @staticmethod
    def clean_lrc(text):
        """清洗歌词：时间戳统一 MM:SS.mmm，删除元数据行"""
        if not text:
            return ""
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            m = TIME_RE.search(stripped)
            if not m:
                continue
            body = TIME_RE.sub("", stripped).strip()
            if not body:
                continue
            if any(kw in body for kw in META_KEYWORDS):
                continue
            if re.match(r"^\S+\s*[-–]\s*\S+$", body) and not re.search(r"[，。！？,.!?]", body):
                continue
            lines.append(TIME_RE.sub(MeowNeteaseMusic._norm_time, stripped))
        return "\n".join(lines) + ("\n" if lines else "")

    @staticmethod
    def _norm_time(match):
        m = int(match.group(1))
        s = int(match.group(2))
        ms = int(match.group(3).ljust(3, "0")[:3])
        return f"[{m:02d}:{s:02d}.{ms:03d}]"

    @staticmethod
    def _safe_name(name):
        return re.sub(r'[\\/:*?"<>|]', "_", str(name or "")).strip() or "未命名"
