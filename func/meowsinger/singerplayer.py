# -*- coding: utf-8 -*-
# func/meowsinger/singerplayer.py
# 唱歌播放器（单例）：mpv 播放，stop 立即失效
import os
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

    def play_file(self, file_path):
        """播放音频文件（mp3/wav），返回是否自然播完（未被 stop）"""
        if not os.path.exists(file_path):
            self.log.error(f"[SingerPlayer] 文件不存在: {file_path}")
            return False
        return self.player.play_file(file_path)

    def play_audio(self, audio, sr):
        """把 numpy 音频写入临时 wav 并播放，返回是否自然播完"""
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

    def stop(self):
        """停止当前播放"""
        self.player.stop()
