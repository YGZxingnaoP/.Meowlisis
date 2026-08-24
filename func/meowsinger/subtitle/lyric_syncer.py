# -*- coding: utf-8 -*-
# func/meowsinger/subtitle/lyric_syncer.py
# 歌词字幕同步：以播放开始时刻为基准，按 lrc 时间戳逐句推送歌词（卡拉OK式单行刷新）
import os
import re
import threading
import time

from func.log.default_log import DefaultLog

TIME_RE = re.compile(r"\[(\d{2}):(\d{2})\.(\d{3})\](.*)")


class MeowLyricSyncer:
    """歌词字幕同步器。

    - start(lines, start_idx, end_idx)：以调用时刻为 t0，逐句推送歌词；
    - stop()：停止并清空字幕（回到待机）。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self._thread = None
        self._stop_event = threading.Event()
        self._lines = []
        self._start_idx = 0
        self._end_idx = 0
        self._offset = 0.0
        self._t0 = 0.0
        self._current = None

    def start(self, lines, start_idx=0, end_idx=None):
        """启动歌词同步。lines 为 [{time, text}]，time 为秒。"""
        if not lines:
            return
        end_idx = len(lines) - 1 if end_idx is None else min(end_idx, len(lines) - 1)
        start_idx = max(0, min(start_idx, end_idx))
        self._lines = lines
        self._start_idx = start_idx
        self._end_idx = end_idx
        self._offset = lines[start_idx]["time"]
        self._stop_event.clear()
        self._current = None
        self._t0 = time.monotonic()
        self._show(start_idx)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop_event.wait(0.2):
            elapsed = time.monotonic() - self._t0
            target = self._start_idx
            for i in range(self._start_idx, self._end_idx + 1):
                if self._lines[i]["time"] - self._offset <= elapsed:
                    target = i
                else:
                    break
            if target != self._current:
                self._show(target)

    def _show(self, idx):
        self._current = idx
        text = (self._lines[idx].get("text") or "").strip()
        if not text:
            return
        try:
            from func.pipeline.get_subtitle import GetSubtitleBridge
            GetSubtitleBridge().send_lyric(text)
        except Exception:
            self.log.exception("[LyricSyncer] 推送歌词失败")

    def stop(self):
        """停止同步并清空字幕"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
        self._thread = None
        try:
            from func.pipeline.get_subtitle import GetSubtitleBridge
            GetSubtitleBridge().clear()
        except Exception:
            self.log.exception("[LyricSyncer] 清空字幕失败")

    @staticmethod
    def parse_lrc_file(lrc_path):
        """解析 lrc 文件，返回 [{time, text}]（time 单位秒）。"""
        if not lrc_path or not os.path.exists(lrc_path):
            return []
        result = []
        try:
            with open(lrc_path, "r", encoding="utf-8") as f:
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
            self.log.exception("[LyricSyncer] 读取歌词异常")
            return []
        return result
