# -*- coding: utf-8 -*-
# func/meowsinger/singerplayer.py
# 唱歌播放器（单例）：分块播放并逐块检查代际，stop 后立即失效，完整播放不被正常语音打断
import os
import uuid
import threading

import soundfile as sf

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.tts.player import AudioPlayer


@singleton
class MeowSingerPlayer:
    """唱歌专用播放器（单例）：点歌/翻唱/即兴哼唱共用

    使用代际 generation 解决 stop 与 AudioPlayer 内部 clear 的竞态：
    播放循环每写一块前检查代际是否变化，stop() 时代际 +1 并停止底层流，
    与底层 _stop_flag.clear 解耦，保证 stop 后播放立即失效。
    """

    CHUNK_FRAMES = 1024

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.player = AudioPlayer()
        self._generation = 0
        self._lock = threading.Lock()

    def play_file(self, file_path):
        """分块播放音频文件，返回是否自然播完（未被 stop）"""
        try:
            data, sr = sf.read(file_path, dtype="int16")
        except Exception as e:
            self.log.error(f"[SingerPlayer] 读取音频失败: {file_path} - {e}")
            return False
        if data is None or data.size == 0:
            return False
        return self._play_int16(data, sr)

    def play_audio(self, audio, sr):
        """把 numpy 音频写入临时文件并播放，返回是否自然播完"""
        tmp_path = os.path.join(".temp", f"sing_{uuid.uuid4().hex}.wav")
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        try:
            sf.write(tmp_path, audio, sr)
            return self.play_file(tmp_path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def _play_int16(self, data, sr):
        """分块播放 int16 数据，每块前检查代际，返回是否自然播完"""
        with self._lock:
            gen = self._generation
        channels = 1 if data.ndim == 1 else data.shape[1]
        raw = data.tobytes()
        frame_bytes = self.CHUNK_FRAMES * channels * 2

        if not self.player.open_stream(int(sr), channels):
            self.log.warning("[SingerPlayer] 打开音频流失败")
            return False
        try:
            for i in range(0, len(raw), frame_bytes):
                with self._lock:
                    if gen != self._generation:
                        return False
                chunk = raw[i:i + frame_bytes]
                if chunk:
                    if not self.player.write(chunk):
                        return False
            return True
        except Exception:
            return False
        finally:
            self.player.close_stream()

    def stop(self):
        """停止当前播放并使后续播放代际失效"""
        with self._lock:
            self._generation += 1
        self.player.stop()
