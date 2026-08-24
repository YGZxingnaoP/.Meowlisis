# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/pass_the_baton/next_line.py
# 接龙定位：定位用户哼唱歌词 + 往后 hum_lines 句接唱（末尾不足取最后两句）
import os
import re

from func.toolbox.meowsongs.config import TBMeowSongsConfig

MEOW_DIR = os.path.join("character", "songs", "meow_list")

TIME_RE = re.compile(r"\[(\d{2}):(\d{2})\.(\d{3})\](.*)")


class TBNextLine:
    """接龙定位：返回用户歌词与接唱起始时间、接唱歌词"""

    def __init__(self):
        self.config = TBMeowSongsConfig()

    def locate(self, song_title, offset_sec, hum_duration):
        """返回 (user_lyric, start_sec, end_sec, next_lines)"""
        lrc = self._load_lrc(song_title)
        if not lrc:
            return "", None, None, []
        hum_lines = max(1, self.config.hum_lines)
        pos = offset_sec + hum_duration

        # 用户唱的歌词：覆盖 offset ~ offset+hum_duration 的所有句
        user_lyric = self._lyrics_in_range(lrc, offset_sec, offset_sec + hum_duration)

        # 往后接唱起始
        start_idx = None
        for i, item in enumerate(lrc):
            if item["time"] > pos:
                start_idx = i
                break
        if start_idx is None:
            start_idx = max(0, len(lrc) - hum_lines)
        end_idx = min(len(lrc), start_idx + hum_lines)

        picked = lrc[start_idx:end_idx]
        if not picked:
            return user_lyric, None, None, []

        # 接唱结束时间：下一句起始，若已是最后则 None（唱到结尾）
        end_sec = None
        if end_idx < len(lrc):
            end_sec = lrc[end_idx]["time"]
        return user_lyric, picked[0]["time"], end_sec, [p["text"] for p in picked]

    def _lyrics_in_range(self, lrc, start_sec, end_sec):
        """返回时间范围内覆盖的所有歌词（去重，用空格连接）"""
        lines = []
        for item in lrc:
            if item["time"] > end_sec:
                break
            if item["time"] >= start_sec and item["text"] not in lines:
                lines.append(item["text"])
        return " ".join(lines)

    def _load_lrc(self, title):
        safe = self._safe_name(title)
        path = os.path.join(MEOW_DIR, safe, f"{safe}.lrc")
        if not os.path.exists(path):
            return []
        result = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f.read().splitlines():
                    m = TIME_RE.match(line.strip())
                    if not m:
                        continue
                    mm, ss, ms = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    result.append({
                        "time": mm * 60 + ss + ms / 1000.0,
                        "text": m.group(4).strip(),
                    })
        except Exception:
            pass
        return result

    @staticmethod
    def _safe_name(name):
        return re.sub(r'[\\/:*?"<>|]', "_", str(name or "")).strip() or "未命名"
