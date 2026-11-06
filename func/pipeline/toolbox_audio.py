# -*- coding: utf-8 -*-
# func/pipeline/toolbox_audio.py
# 音频旁路桥接：把各音频源（mic / loopback / inject）的帧分发给哼唱检测与落盘缓存
import os
import time
import threading
import wave

import numpy as np

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.meowsongs.config import TBMeowSongsConfig

SAMPLE_RATE = 16000
DEFAULT_SOURCE = "mic"


def _src_key(sid):
    """音频源 → ASR 回调里的 source 标识（用于按来源丢弃 ASR）"""
    return "phone" if sid == "inject" else "llm"


@singleton
class ToolboxAudioBridge:
    """音频旁路桥接（单例）：连接各音频源与 meowsongs，唯一音频分发通道

    每个音频源（mic / loopback / inject）各有一份哼唱状态与结果，
    通过 sid 区分，互不干扰。
    """

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBMeowSongsConfig()
        self._lock = threading.RLock()
        self._hum_end_lock = threading.Lock()
        self._last_hum_audio = {}      # sid -> 落盘 wav 路径
        self._last_speaker = ""
        self._discard_next_asr = {}    # src_key('llm'/'phone') -> bool
        self._last_hum_seq = {}        # sid -> 已处理到的事件序号

    def set_last_speaker(self, uid):
        """写入最近一次通过声纹验证的说话人（供哼唱记忆绑定用户）"""
        if uid:
            with self._lock:
                self._last_speaker = uid

    def get_last_speaker(self):
        """读取最近一次通过声纹验证的说话人"""
        with self._lock:
            return self._last_speaker or ""

    def get_hum_duration(self, sid=DEFAULT_SOURCE):
        """读取指定源最近一段哼唱的完整时长（秒），供接唱定位 offset+时长"""
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            return TBHumDetect().get_last_hum_duration(sid)
        except Exception:
            return 0.0

    def get_hum_event_type(self, sid=DEFAULT_SOURCE):
        """读取指定源最近一次哼唱事件类型（"lock" 或 "sing"）"""
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            return TBHumDetect().get_last_event_type(sid)
        except Exception:
            return ""

    def is_last_hum(self, sid=DEFAULT_SOURCE):
        """指定源最近一段是否判为哼唱（供声纹按域选模板；功能未启用时恒为 False）"""
        if not self.config.pbt_enabled:
            return False
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            return TBHumDetect().is_last_segment_hum(sid)
        except Exception:
            return False

    def reset_source(self, sid):
        """丢弃指定源的哼唱状态与缓存（源被关闭/重建时调用）"""
        if not sid:
            return
        with self._hum_end_lock:
            self._last_hum_audio.pop(sid, None)
        with self._lock:
            self._last_hum_seq.pop(sid, None)
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            TBHumDetect().reset(sid)
        except Exception:
            pass

    def dispatch_frame(self, frame: bytes, sid=DEFAULT_SOURCE):
        """接收一帧 16k 单声道 PCM：喂该源的哼唱检测 + 检测哼唱事件"""
        if not self.config.pbt_enabled:
            return
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            TBHumDetect().feed(frame, sid)
        except Exception:
            self.log.exception(f"[ToolboxAudio] 哼唱检测分发异常 sid={sid}")

        try:
            # 检测哼唱段完成事件（事件序号变化 → 有新哼唱段）
            self._check_hum_event(sid)
        except Exception:
            self.log.exception(f"[ToolboxAudio] 哼唱事件检测异常 sid={sid}")

    def _check_hum_event(self, sid):
        """检测指定源的检测器是否产生新事件，有则落盘并触发匹配"""
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            seq = TBHumDetect().get_hum_event_seq(sid)
        except Exception:
            return
        if seq != self._last_hum_seq.get(sid, 0):
            self._last_hum_seq[sid] = seq
            self._dump_hum_audio(sid)

    def should_discard_next_asr(self, source=""):
        """查询并复位「丢弃下一条 ASR」标志（哼唱结束后调用，下一条 final 丢弃）

        source 为 ASR 回调里的来源标识（'llm' / 'phone'）；按来源分别记账，
        免得手机的哼唱把电脑那边的 ASR 吃掉。source 未知时任一挂起都算。
        """
        with self._lock:
            key = source if source in ("llm", "phone") else ""
            if key:
                if self._discard_next_asr.get(key):
                    self._discard_next_asr[key] = False
                    return True
                return False
            for k in list(self._discard_next_asr.keys()):
                if self._discard_next_asr[k]:
                    self._discard_next_asr[k] = False
                    return True
            return False

    def consume_hum_audio(self, sid=DEFAULT_SOURCE):
        """取出指定源最近一次哼唱落盘的音频路径并清除（匹配后调用）"""
        with self._hum_end_lock:
            p = self._last_hum_audio.get(sid)
            self._last_hum_audio[sid] = None
            return p

    def _dump_hum_audio(self, sid):
        """落盘指定源当前段哼唱音频并触发匹配；接唱事件无音频也触发"""
        try:
            from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
            detect = TBHumDetect()
            # 事件类型在触发时绑定，避免异步线程读到被后续事件覆盖的值
            event_type = detect.get_last_event_type(sid)
            need_discard = detect.get_and_clear_need_discard(sid)
            audio = detect.consume_hum_audio(sid)

            # 丢弃标志与落盘成败无关：先记账，避免磁盘异常时把哼唱对应的 ASR 放过去
            if need_discard:
                with self._lock:
                    self._discard_next_asr[_src_key(sid)] = True

            path = None
            if audio is not None and audio.size > 0:
                try:
                    os.makedirs(os.path.join(".temp", "user_audio"), exist_ok=True)
                    path = os.path.join(".temp", "user_audio",
                                        f"hum_{sid}_{int(time.time() * 1000)}.wav")
                    with wave.open(path, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(SAMPLE_RATE)
                        wf.writeframes((np.clip(audio, -32768, 32767).astype(np.int16)).tobytes())
                    with self._hum_end_lock:
                        self._last_hum_audio[sid] = path
                    self.log.info(f"[ToolboxAudio] 哼唱音频已落盘({sid}): {path}")
                except Exception:
                    path = None
                    self.log.exception(f"[ToolboxAudio] 哼唱落盘失败({sid})，改用无音频兜底")

            # 事件类型与音频路径在触发时绑定，避免异步线程读共享变量被覆盖
            from threading import Thread
            Thread(target=self._trigger_baton, args=(sid, event_type, path), daemon=True).start()
        except Exception:
            self.log.exception(f"[ToolboxAudio] 落盘哼唱音频异常 sid={sid}")

    def _trigger_baton(self, sid, event_type, path):
        """落盘后异步触发听歌识曲接龙匹配（来源/事件类型/路径已绑定）"""
        try:
            from func.toolbox.meowsongs.pass_the_baton.pass_the_baton import TBPassTheBaton
            TBPassTheBaton().run(event_type, path, sid)
        except Exception:
            self.log.exception(f"[ToolboxAudio] 触发接龙匹配异常 sid={sid}")
