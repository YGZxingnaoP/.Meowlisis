# -*- coding: utf-8 -*-
# func/database/song_review/get_lyrics.py
# 读取歌曲歌词（点歌读 raw_list，翻唱读 meow_list）
import os
import re


class MeowSongGetLyrics:
    """歌词读取：按模式从对应文件夹读取完整歌词"""

    def read(self, song_title, mode):
        title = self._safe_name(song_title)
        base = "meow_list" if mode == "cover" else "raw_list"
        lrc_path = os.path.join("character", "songs", base, title, f"{title}.lrc")
        if not os.path.exists(lrc_path):
            return ""
        try:
            with open(lrc_path, "r", encoding="utf-8") as f:
                return self._strip_timestamps(f.read())
        except Exception:
            return ""

    @staticmethod
    def _strip_timestamps(text):
        lines = []
        for line in (text or "").splitlines():
            body = re.sub(r"\[\d{1,2}:\d{2}\.\d{1,3}\]", "", line).strip()
            if body:
                lines.append(body)
        return "\n".join(lines)

    @staticmethod
    def _safe_name(name):
        return re.sub(r'[\\/:*?"<>|]', "_", str(name or "")).strip() or "未命名"
