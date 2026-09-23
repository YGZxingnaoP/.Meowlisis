# -*- coding: utf-8 -*-
# func/meowsinger/singerplayer.py
# 唱歌播放器（单例）：mpv 播放，stop 立即失效
import os
import threading
import time
import uuid

import soundfile as sf

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.tts.player import AudioPlayer


@singleton
class MeowSingerPlayer:
    """唱歌专用播放器（单例）：点歌/翻唱/即兴哼唱共用"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.player = AudioPlayer()
        # 手机镜像（哼唱/翻唱也给手机听）：与本地播放并行，按 1x 速率推送
        self._mirror_stop = threading.Event()
        self._mirror_thread = None

    def play_file(self, file_path):
        """播放音频文件（mp3/wav），返回是否自然播完（未被 stop）"""
        if not os.path.exists(file_path):
            self.log.error(f"[SingerPlayer] file not found: {file_path}")
            return False
        self._start_mirror_file(file_path)
        try:
            return self.player.play_file(file_path)
        finally:
            self._stop_mirror()


    def play_audio(self, audio, sr):
        """把 numpy 音频写入临时 wav 并播放，返回是否自然播完"""
        self._start_mirror_pcm(self._to_pcm(audio), int(sr or 32000))
        tmp_path = os.path.join(".temp", f"sing_{uuid.uuid4().hex}.wav")
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        try:
            sf.write(tmp_path, audio, sr)
            return self.player.play_file(tmp_path)
        finally:
            self._stop_mirror()
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass


    def stop(self):
        """停止当前播放"""
        self._stop_mirror()
        self.player.stop()

    # ==================== 手机镜像（哼唱/翻唱也给手机听） ====================
    @staticmethod
    def _to_pcm(audio):
        """numpy 音频 -> 单声道 int16 PCM 字节（失败返回空）"""
        try:
            import numpy as np
            arr = np.asarray(audio)
            if arr.size == 0:
                return b""
            if arr.ndim > 1 and arr.shape[1] > 1:
                arr = arr.mean(axis=1)
            arr = arr.reshape(-1)
            if arr.dtype != np.int16:
                arr = np.clip(arr, -1.0, 1.0) * 32767.0
                arr = arr.astype(np.int16)
            return arr.tobytes()
        except Exception:
            return b""

    def _start_mirror_file(self, file_path):
        """文件播放：线程内解码后再按 1x 速率推（不阻塞本地播放）"""
        self._stop_mirror()
        self._mirror_stop.clear()
        self._mirror_thread = threading.Thread(
            target=self._mirror_from_file, args=(file_path,), daemon=True,
            name="singer-mirror")
        self._mirror_thread.start()

    def _start_mirror_pcm(self, pcm, sr):
        """已知 PCM：直接起推送线程"""
        self._stop_mirror()
        if not pcm:
            return
        self._mirror_stop.clear()
        self._mirror_thread = threading.Thread(
            target=self._mirror_loop, args=(pcm, sr), daemon=True,
            name="singer-mirror")
        self._mirror_thread.start()

    def _mirror_from_file(self, file_path):
        """线程内解码文件 -> 单声道 int16 PCM"""
        try:
            data, sr = sf.read(file_path, dtype="int16", always_2d=True)
            if data is None or data.size == 0:
                return
            if data.shape[1] > 1:
                pcm = data.mean(axis=1).astype("int16").tobytes()
            else:
                pcm = data[:, 0].tobytes()
        except Exception as e:
            self.log.warning(f"[SingerPlayer] mirror decode failed: {e}")
            return
        self._mirror_loop(pcm, int(sr or 32000))

    def _mirror_loop(self, pcm, sr):
        """按 1x 实时速率分块推给手机（先多送一点做抖动缓冲）"""
        bridge = None
        try:
            from func.tts.tts_core import TTsCore
            bridge = TTsCore().tts_phone
        except Exception as e:
            self.log.warning(f"[SingerPlayer] phone bridge unavailable: {e}")
            return
        if bridge is None:
            return
        sr = int(sr or 32000)
        per = max(2048, int(sr * 0.25) * 2)
        per -= per % 2
        lead = 4
        sent = 0
        idx = 0
        try:
            bridge.start_stream("", "", sample_rate=sr, source="hum")
        except Exception:
            return
        try:
            while idx < len(pcm) and not self._mirror_stop.is_set():
                try:
                    bridge.push(pcm[idx:idx + per])
                except Exception:
                    pass
                idx += per
                sent += 1
                if sent > lead:
                    time.sleep(0.25)
        finally:
            try:
                bridge.end_stream()
            except Exception:
                pass

    def _stop_mirror(self):
        """停止镜像线程（并让手机侧收尾）"""
        self._mirror_stop.set()
        th = self._mirror_thread
        self._mirror_thread = None
        if th and th.is_alive():
            th.join(timeout=0.8)

