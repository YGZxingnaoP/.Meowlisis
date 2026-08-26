# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/pass_the_baton/hum_match.py
# 哼唱匹配：音高序列（QBH）滑动窗口余弦相似度，vocal 音高缓存为 npy 复用
import os
import threading

import numpy as np

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.meowsongs.config import TBMeowSongsConfig

MEOW_DIR = os.path.join("character", "songs", "meow_list")
HOP = 256
SR = 16000


@singleton
class TBHumMatch:
    """哼唱匹配（单例）：vocal 音高序列缓存为 npy，匹配时读缓存"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBMeowSongsConfig()
        self._lock = threading.Lock()
        self._refs = {}
        self._loaded = False

    def build_pitch_cache(self, title, vocal_path=None):
        """为一首歌生成音高缓存 npy（学歌时调用），返回是否成功"""
        try:
            title = self._safe_name(title)
            if not vocal_path:
                vocal_path = os.path.join(MEOW_DIR, title, f"{title}_vocal.wav")
            if not os.path.exists(vocal_path):
                return False
            seq = self._extract_midi(vocal_path)
            if seq is None or seq.size == 0:
                return False
            npy_path = self._pitch_path(title)
            np.save(npy_path, seq)
            # 同步刷新内存缓存
            with self._lock:
                self._refs[title] = seq
            return True
        except Exception:
            self.log.exception(f"[HumMatch] 生成音高缓存失败: {title}")
            return False

    def _load_refs(self):
        with self._lock:
            if self._loaded:
                return
            for title in self._list_titles():
                seq = self._load_or_build(title)
                if seq is not None and seq.size > 0:
                    self._refs[title] = seq
            self._loaded = True

    def _load_or_build(self, title):
        """优先读 npy，缺失则补生成"""
        npy_path = self._pitch_path(title)
        if os.path.exists(npy_path):
            try:
                return np.load(npy_path)
            except Exception:
                self.log.exception(f"[HumMatch] 读取音高缓存失败: {title}")
        # 补生成
        vocal = os.path.join(MEOW_DIR, title, f"{title}_vocal.wav")
        seq = self._extract_midi(vocal)
        if seq is not None and seq.size > 0:
            try:
                np.save(npy_path, seq)
            except Exception:
                self.log.exception(f"[HumMatch] 保存音高缓存失败: {title}")
        return seq

    def match(self, hum_wav):
        """返回 (song_title, offset_sec, score)。未达阈值时 song_title 为 None，score 仍为最高分"""
        self._load_refs()
        if not self._refs:
            return None, 0.0, 0.0
        hum_seq = self._extract_midi(hum_wav)
        if hum_seq is None or hum_seq.size < 3:
            return None, 0.0, 0.0

        best_title, best_offset, best_score = None, 0.0, 0.0
        for title, ref in self._refs.items():
            if ref.size < hum_seq.size:
                continue
            score, offset = self._slide_cosine(ref, hum_seq)
            if score > best_score:
                best_title, best_score, best_offset = title, score, offset
        if best_title is None or best_score < self.config.match_threshold:
            return None, best_offset, best_score
        return best_title, best_offset, best_score

    def _slide_cosine(self, ref, query):
        """滑动窗口余弦相似度，返回 (最高分, 偏移秒)"""
        q = query
        q_norm = np.linalg.norm(q) + 1e-8
        best, best_idx = -1.0, 0
        for i in range(0, ref.size - q.size + 1):
            window = ref[i:i + q.size]
            w_norm = np.linalg.norm(window) + 1e-8
            score = float(np.dot(window, q) / (w_norm * q_norm))
            if score > best:
                best, best_idx = score, i
        offset = best_idx * HOP / SR
        return best, offset

    def _extract_midi(self, path):
        """提取音频 F0 序列并转为去均值半音（yin，无 Viterbi 平滑，速度快）"""
        try:
            import librosa
            audio, sr = librosa.load(path, sr=SR, mono=True)
            f0 = librosa.yin(
                audio, fmin=80, fmax=800,
                sr=SR, frame_length=2048, hop_length=HOP,
            )
            valid = f0[~np.isnan(f0)]
            if valid.size < 3:
                return None
            midi = 12.0 * np.log2(valid / 440.0) + 69.0
            midi = midi - np.mean(midi)
            return midi.astype(np.float32)
        except Exception:
            self.log.exception(f"[HumMatch] 提取音高失败: {path}")
            return None

    def _list_titles(self):
        if not os.path.isdir(MEOW_DIR):
            return []
        return [d for d in os.listdir(MEOW_DIR)
                if os.path.isdir(os.path.join(MEOW_DIR, d))
                and os.path.exists(os.path.join(MEOW_DIR, d, f"{d}_vocal.wav"))]

    @staticmethod
    def _pitch_path(title):
        return os.path.join(MEOW_DIR, title, f"{title}_pitch.npy")

    @staticmethod
    def _safe_name(name):
        import re
        return re.sub(r'[\\/:*?"<>|]', "_", str(name or "")).strip() or "未命名"
