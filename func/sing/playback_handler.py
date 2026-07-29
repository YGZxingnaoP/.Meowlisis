# -*- coding: utf-8 -*-
import os
import time
import re
import subprocess
from threading import Thread

class PlaybackHandler:
    def __init__(self, song_cache_dir, log, subtitle_server=None):
        self.song_cache_dir = song_cache_dir
        self.log = log
        self.subtitle_server = subtitle_server
        self.current_mpv_process = None
        self.stop_requested = False
        self.sing_play_flag = 0

    def send_lyric_subtitle(self, text):
        if self.subtitle_server:
            try:
                self.subtitle_server.send_subtitle(text)
                self.log.info(f"[字幕] 发送歌词: {text[:50]}{'...' if len(text)>50 else ''}")
            except Exception as e:
                self.log.error(f"发送歌词字幕失败: {e}")
        else:
            self.log.error("字幕服务器为 None，无法发送歌词")

    def _launch_mpv(self, path, start=0, end=None):
        startupinfo = None
        creationflags = 0
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        cmd = [
            "mpv.exe",
            "--no-video",
            "--no-terminal",
            "--msg-level=all=no",
            path,
            "--volume=70",
            f"--start={start}"
        ]
        if end is not None:
            cmd.append(f"--end={end}")
        return subprocess.Popen(
            cmd,
            startupinfo=startupinfo,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    def play_audio_only(self, mp3_path):
        self.sing_play_flag = 1
        self.current_mpv_process = self._launch_mpv(mp3_path)
        self.current_mpv_process.wait()
        self.sing_play_flag = 0
        self.current_mpv_process = None

    def _parse_lrc_sentences(self, lrc_path):
        """
        解析 LRC 文件，格式: [mm:ss.xx] 或 [mm:ss.xxx]
        返回 [(timestamp_sec, text), ...]
        """
        sentences = []
        try:
            with open(lrc_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # 匹配 [mm:ss.xx] 或 [mm:ss.xxx]
                    pattern = r'\[(\d{2}):(\d{2})(?:\.(\d{1,3}))?\]'
                    matches = re.findall(pattern, line)
                    if matches:
                        for m in matches:
                            minutes = int(m[0])
                            seconds = int(m[1])
                            millis_str = m[2] if len(m) > 2 else None
                            if millis_str:
                                millis = int(millis_str)
                                if len(millis_str) == 2:
                                    millis *= 10
                                elif len(millis_str) == 1:
                                    millis *= 100
                            else:
                                millis = 0
                            total_sec = minutes * 60 + seconds + millis / 1000.0
                            lyric_text = re.sub(pattern, '', line).strip()
                            if lyric_text:
                                sentences.append((total_sec, lyric_text))
                                break  # 只取第一个时间戳
        except Exception as e:
            self.log.warning(f"解析歌词文件失败 {lrc_path}: {e}")
        return sentences

    def play_with_lyrics(self, mp3_path):
        self.log.info(f"=== play_with_lyrics 开始，mp3: {mp3_path} ===")
        base_name = os.path.splitext(os.path.basename(mp3_path))[0]
        if base_name.startswith("[喵呜翻唱]"):
            base_name = base_name[len("[喵呜翻唱]"):]
        lrc_path = os.path.join(self.song_cache_dir, f"{base_name}.lrc")
        if not os.path.exists(lrc_path):
            self.play_audio_only(mp3_path)
            return

        sentences = self._parse_lrc_sentences(lrc_path)
        if not sentences:
            self.play_audio_only(mp3_path)
            return

        if self.subtitle_server is None:
            self.play_audio_only(mp3_path)
            return

        self.stop_requested = False
        self.sing_play_flag = 1
        start_time = time.time()
        self.current_mpv_process = self._launch_mpv(mp3_path)

        def subtitle_worker():
            idx = 0
            last_sent = -1
            timestamps = [ts for ts, _ in sentences]
            while not self.stop_requested and self.current_mpv_process is not None:
                elapsed = time.time() - start_time
                # 允许0.5秒误差
                while idx < len(timestamps) and timestamps[idx] <= elapsed + 0.5:
                    idx += 1
                for i in range(last_sent + 1, idx):
                    self.send_lyric_subtitle(sentences[i][1])
                last_sent = idx - 1
                if self.current_mpv_process.poll() is not None:
                    break
                time.sleep(0.05)
            time.sleep(1)
            self.send_lyric_subtitle("")

        Thread(target=subtitle_worker, daemon=True).start()
        self.current_mpv_process.wait()
        self.sing_play_flag = 0
        self.current_mpv_process = None
        self.send_lyric_subtitle("")

    def play_fragment_with_lyrics(self, mp3_path, start_sec, end_sec, sentences):
        filtered = []
        for ts, text in sentences:
            if start_sec <= ts <= end_sec:
                filtered.append((ts - start_sec, text))
        if not filtered:
            self.play_fragment(mp3_path, start_sec, end_sec - start_sec)
            return

        self.stop_requested = False
        self.sing_play_flag = 1
        self.current_mpv_process = self._launch_mpv(mp3_path, start_sec, end_sec)

        def subtitle_worker():
            for offset, text in filtered:
                if self.stop_requested or self.current_mpv_process is None:
                    break
                wait_start = time.time()
                while time.time() - wait_start < offset:
                    if self.stop_requested:
                        return
                    time.sleep(0.05)
                if not self.stop_requested:
                    self.send_lyric_subtitle(text)
            time.sleep(1)
            self.send_lyric_subtitle("")

        Thread(target=subtitle_worker, daemon=True).start()
        self.current_mpv_process.wait()
        self.sing_play_flag = 0
        self.current_mpv_process = None
        self.send_lyric_subtitle("")

    def play_fragment(self, mp3_path, start_sec, duration_sec):
        cmd = [
            "mpv.exe",
            "--no-video",
            "--no-terminal",
            f"--start={start_sec}",
            f"--end={start_sec + duration_sec}",
            mp3_path
        ]
        startupinfo = None
        creationflags = 0
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        self.current_mpv_process = subprocess.Popen(
            cmd,
            startupinfo=startupinfo,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        def wait_end():
            self.current_mpv_process.wait()
            if self.current_mpv_process == self.current_mpv_process:
                self.current_mpv_process = None
        Thread(target=wait_end, daemon=True).start()

    def stop(self):
        if self.current_mpv_process:
            pid = self.current_mpv_process.pid
            try:
                self.current_mpv_process.terminate()
                self.current_mpv_process.wait(timeout=1)
            except:
                pass
            if self.current_mpv_process.poll() is None:
                try:
                    subprocess.run(
                        ['taskkill', '/F', '/T', '/PID', str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3
                    )
                except:
                    pass
            self.current_mpv_process = None
        self.sing_play_flag = 0
        self.stop_requested = True