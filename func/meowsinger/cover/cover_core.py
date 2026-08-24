# -*- coding: utf-8 -*-
# func/meowsinger/cover/cover_core.py
# 翻唱核心：调 RVC 服务分离三轨与变声，保存到 meow_list，混音播放
import os
import shutil

import numpy as np
import requests
import soundfile as sf

from func.log.default_log import DefaultLog
from func.meowsinger.config import MeowSingerConfig

MEOW_DIR = os.path.join("character", "songs", "meow_list")
RAW_DIR = os.path.join("character", "songs", "raw_list")


class MeowCoverCore:
    """翻唱核心：人声分离、RVC 变声、混音播放（音频处理全在模块内部）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = MeowSingerConfig()

    def separate(self, input_path, output_dir):
        """调 RVC 服务分离人声/伴奏/和声，返回三轨路径 dict"""
        try:
            resp = requests.post(
                f"{self.config.rvc_url}/api/separate",
                json={"input_path": input_path, "output_dir": output_dir},
                timeout=600,
            )
            data = resp.json()
            if data.get("code") != 200:
                self.log.error(f"[Cover] 分离失败: {data.get('msg')}")
                return None
            return {
                "vocal": data.get("vocal_path"),
                "accomp": data.get("accomp_path"),
                "harmony": data.get("harmony_path"),
            }
        except Exception:
            self.log.exception("[Cover] 调 RVC 分离异常")
            return None

    def convert(self, vocal_path, output_path):
        """调 RVC 服务把分离出的人声变声，返回输出路径"""
        try:
            resp = requests.post(
                f"{self.config.rvc_url}/api/convert",
                json={
                    "model": self.config.rvc_model,
                    "index": self.config.rvc_index,
                    "input_path": vocal_path,
                    "output_path": output_path,
                    "f0_up_key": 0,
                    "f0_method": "rmvpe",
                    "index_rate": 0.75,
                    "protect": 0.33,
                },
                timeout=600,
            )
            data = resp.json()
            if data.get("code") != 200:
                self.log.error(f"[Cover] 变声失败: {data.get('msg')}")
                return ""
            return data.get("output_path", "")
        except Exception:
            self.log.exception("[Cover] 调 RVC 变声异常")
            return ""

    def learn_song(self, title, mp3_path):
        """学习一首歌：分离 → 变声 → 三轨与歌词保存到 meow_list，返回是否成功"""
        title = self._safe_name(title)
        folder = os.path.join(MEOW_DIR, title)
        os.makedirs(folder, exist_ok=True)

        separated = self.separate(mp3_path, folder)
        if not separated or not separated.get("vocal"):
            return False

        cover_path = os.path.join(folder, f"{title}_vocal.wav")
        converted = self.convert(separated["vocal"], cover_path)
        if not converted or not os.path.exists(converted):
            return False

        if converted != cover_path:
            shutil.move(converted, cover_path)

        if separated.get("accomp"):
            try:
                shutil.copy(separated["accomp"], os.path.join(folder, f"{title}_accomp.wav"))
            except Exception:
                self.log.exception("[Cover] 复制伴奏失败")
        if separated.get("harmony"):
            try:
                shutil.copy(separated["harmony"], os.path.join(folder, f"{title}_harmony.wav"))
            except Exception:
                self.log.exception("[Cover] 复制和声失败")

        lrc_src = os.path.join(RAW_DIR, title, f"{title}.lrc")
        if os.path.exists(lrc_src):
            try:
                shutil.copy(lrc_src, os.path.join(folder, f"{title}.lrc"))
            except Exception:
                self.log.exception("[Cover] 复制歌词失败")

        # 生成音高缓存 npy（学歌成功即生成，失败下次启动补生成）
        try:
            from func.toolbox.meowsongs.pass_the_baton.hum_match import TBHumMatch
            TBHumMatch().build_pitch_cache(title, cover_path)
        except Exception:
            self.log.exception("[Cover] 生成音高缓存失败")
        return True

    def mix_tracks(self, vocal_path, accomp_path, harmony_path):
        """把三轨对齐长度混音，返回 (audio, sr) 或 None"""
        try:
            vocal, sr = sf.read(vocal_path, dtype="float32")
            tracks = [self._to_stereo(vocal, sr)]
            for p in (accomp_path, harmony_path):
                if p and os.path.exists(p):
                    data, rate = sf.read(p, dtype="float32")
                    if rate != sr:
                        data = self._resample(data, rate, sr)
                    tracks.append(self._to_stereo(data, sr))
            if not tracks:
                return None
            min_len = min(t.shape[0] for t in tracks)
            mixed = sum(t[:min_len] for t in tracks)
            mixed = np.clip(mixed, -1.0, 1.0)
            return mixed.astype(np.float32), sr
        except Exception:
            self.log.exception("[Cover] 混音失败")
            return None

    def _to_stereo(self, data, sr):
        if data.ndim == 1:
            return np.column_stack([data, data])
        return data

    def _resample(self, data, orig_sr, target_sr):
        import librosa
        if data.ndim == 1:
            return librosa.resample(data, orig_sr=orig_sr, target_sr=target_sr)
        return librosa.resample(data.T, orig_sr=orig_sr, target_sr=target_sr).T

    def has_learned(self, title):
        title = self._safe_name(title)
        folder = os.path.join(MEOW_DIR, title)
        vocal = os.path.join(folder, f"{title}_vocal.wav")
        accomp = os.path.join(folder, f"{title}_accomp.wav")
        return os.path.exists(vocal) and os.path.exists(accomp)

    def raw_mp3_path(self, title):
        title = self._safe_name(title)
        return os.path.join(RAW_DIR, title, f"{title}.mp3")

    @staticmethod
    def _safe_name(name):
        import re
        return re.sub(r'[\\/:*?"<>|]', "_", str(name or "")).strip() or "未命名"
