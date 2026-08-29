# -*- coding: utf-8 -*-
# func/pipeline/audio_state.py
# 项目内音频播放状态（TTS / 唱歌统一汇总），供电脑扬声器采集静音判断

from func.tools.singleton_mode import singleton


@singleton
class AudioState:
    """项目内音频播放状态

    - TTS、唱歌等模块播放开始/结束时更新状态；
    - 电脑扬声器(loopback)采集侧查询 is_playing()，播放期间把采集帧转为静音帧。
    """

    def __init__(self):
        self._playing = False

    def set_playing(self, playing: bool):
        """写入播放状态（True=播放中，False=停止）"""
        self._playing = bool(playing)

    def is_playing(self) -> bool:
        """项目内是否有音频在播放（TTS 或唱歌）"""
        return self._playing
