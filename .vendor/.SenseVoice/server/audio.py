# -*- coding: utf-8 -*-
# server/audio.py - 音频工具

import tempfile
import wave

SAMPLE_RATE = 16000


def save_audio_to_wav(audio_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> str:
    """PCM 音频字节保存为临时 WAV，返回文件路径"""
    tmp_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    with wave.open(tmp_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)
    return tmp_path
