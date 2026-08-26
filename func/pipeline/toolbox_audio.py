# -*- coding: utf-8 -*-
# func/pipeline/toolbox_audio.py
# 音频旁路桥接：把 SenseVoice 采集的帧分发给哼唱检测与落盘缓存
import os
import time
import threading
import wave

import numpy as np

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.meowsongs.config import TBMeowSongsConfig

SAMPLE_RATE = 16000


@singleton
class ToolboxAudioBridge:
    """音频旁路桥接（单例）：连接 SenseVoice 与 meowsongs，唯一音频分发通道"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBMeowSongsConfig()
        self._lock = threading.RLock()
        self._hum_end_lock = threading.Lock()
        self._last_hum_audio = None
        self._last_speaker = ""
        self._discard_next_asr = False
        self._last_hum_seq = 0

    def set_last_speaker(self, username):
        """写入最近一次通过声纹验证的说话人（供哼唱记忆绑定用户）"""
        if username:
            with self._lock:
                self._last_speaker = username

    def get_last_speaker(self):
        """读取最近一次通过声纹验证的说话人"""
        with self._lock:
            return self._last_speaker or ""

    def get_hum_duration(self):
        """读取最近一段哼唱的完整时长（秒），供接唱定位 offset+时长"""
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            return TBHumDetect().get_last_hum_duration()
        except Exception:
            return 0.0

    def get_hum_event_type(self):
        """读取最近一次哼唱事件类型（"lock" 或 "sing"）"""
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            return TBHumDetect().get_last_event_type()
        except Exception:
            return ""

    def dispatch_frame(self, frame: bytes):
        """接收一帧 16k 单声道 PCM：喂哼唱检测 + 检测哼唱事件"""
        if not self.config.pbt_enabled:
            return
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            TBHumDetect().feed(frame)
        except Exception:
            self.log.exception("[ToolboxAudio] 哼唱检测分发异常")

        try:
            # 检测哼唱段完成事件（事件序号变化 → 有新哼唱段）
            self._check_hum_event()
        except Exception:
            self.log.exception("[ToolboxAudio] 哼唱事件检测异常")

    def _check_hum_event(self):
        """检测哼唱检测器是否产生新事件，有则落盘并触发匹配"""
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            seq = TBHumDetect().get_hum_event_seq()
        except Exception:
            return
        if seq != self._last_hum_seq:
            self._last_hum_seq = seq
            self._dump_hum_audio()

    def should_discard_next_asr(self):
        """查询并复位「丢弃下一条 ASR」标志（哼唱结束后调用，下一条 final 丢弃）"""
        with self._lock:
            flag = self._discard_next_asr
            self._discard_next_asr = False
            return flag

    def consume_hum_audio(self):
        """取出最近一次哼唱落盘的音频路径并清除（匹配后调用）"""
        with self._hum_end_lock:
            p = self._last_hum_audio
            self._last_hum_audio = None
            return p

    def _dump_hum_audio(self):
        """落盘当前段哼唱音频并触发匹配；接唱事件无音频也触发"""
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            detect = TBHumDetect()
            # 事件类型在触发时绑定，避免异步线程读到被后续事件覆盖的值
            event_type = detect.get_last_event_type()
            need_discard = detect.get_and_clear_need_discard()
            audio = detect.consume_hum_audio()

            path = None
            if audio is not None and audio.size > 0:
                os.makedirs(os.path.join(".temp", "user_audio"), exist_ok=True)
                path = os.path.join(".temp", "user_audio", f"hum_{int(time.time()*1000)}.wav")
                with wave.open(path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes((np.clip(audio, -32768, 32767).astype(np.int16)).tobytes())
                with self._hum_end_lock:
                    self._last_hum_audio = path
                self.log.info(f"[ToolboxAudio] 哼唱音频已落盘: {path}")

            # 只在判定成功的那一次设置丢弃标志（丢弃哼唱对应的 ASR final，只丢一次）
            if need_discard:
                with self._lock:
                    self._discard_next_asr = True

            # 事件类型与音频路径在触发时绑定，避免异步线程读共享变量被覆盖
            from threading import Thread
            Thread(target=self._trigger_baton, args=(event_type, path), daemon=True).start()
        except Exception:
            self.log.exception("[ToolboxAudio] 落盘哼唱音频异常")

    def _trigger_baton(self, event_type, path):
        """落盘后异步触发听歌识曲接龙匹配（事件类型/路径已绑定）"""
        try:
            from func.toolbox.meowsongs.pass_the_baton.pass_the_baton import TBPassTheBaton
            TBPassTheBaton().run(event_type, path)
        except Exception:
            self.log.exception("[ToolboxAudio] 触发接龙匹配异常")
