# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/pass_the_baton/hum_match.py
# 哼唱匹配：yin 音高序列（全曲去均值）→ 全库向量化滑窗余弦 → 取最佳位置作为 offset
import os
import threading

import numpy as np

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.meowsongs.config import TBMeowSongsConfig

MEOW_DIR = os.path.join("character", "songs", "meow_list")
HOP = 256
SR = 16000
FRAME_LENGTH = 2048
F0_MIN = 80.0
F0_MAX = 800.0


@singleton
class TBHumMatch:
    """哼唱匹配（单例）：vocal 音高序列缓存为 npy，匹配时读缓存"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBMeowSongsConfig()
        self._lock = threading.Lock()
        self._refs = {}
        self._loaded = False

    # ==================== 音高缓存 ====================
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
            np.save(self._pitch_path(title), seq)
            # 同步刷新内存缓存
            with self._lock:
                self._refs[title] = seq
            return True
        except Exception:
            self.log.exception(f"[HumMatch] 生成音高缓存失败: {title}")
            return False

    def _load_refs(self):
        """载入曲库音高缓存；构建过程不持锁，避免阻塞并发的匹配与学歌"""
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
        refs = {}
        for title in self._list_titles():
            seq = self._load_or_build(title)
            if seq is not None and seq.size > 0:
                refs[title] = seq
        with self._lock:
            self._refs.update(refs)

    def _load_or_build(self, title):
        """优先读 npy，缺失则补生成"""
        npy_path = self._pitch_path(title)
        if os.path.exists(npy_path):
            try:
                return np.load(npy_path)
            except Exception:
                self.log.exception(f"[HumMatch] 读取音高缓存失败: {title}")
        vocal = os.path.join(MEOW_DIR, title, f"{title}_vocal.wav")
        seq = self._extract_midi(vocal)
        if seq is not None and seq.size > 0:
            try:
                np.save(npy_path, seq)
            except Exception:
                self.log.exception(f"[HumMatch] 保存音高缓存失败: {title}")
        return seq

    def _list_titles(self):
        if not os.path.isdir(MEOW_DIR):
            return []
        return [d for d in os.listdir(MEOW_DIR)
                if os.path.isdir(os.path.join(MEOW_DIR, d))
                and os.path.exists(os.path.join(MEOW_DIR, d, f"{d}_vocal.wav"))]

    def _pitch_path(self, title):
        return os.path.join(MEOW_DIR, title, f"{title}_pitch.npy")

    @staticmethod
    def _safe_name(name):
        import re
        return re.sub(r'[\\/:*?"<>|]', "_", str(name or "")).strip() or "未命名"

    # ==================== 音高提取 ====================
    def _extract_midi(self, path):
        """提取音频 F0 序列并转为去均值半音（yin，无 Viterbi 平滑，速度快）"""
        try:
            import librosa
            audio, _ = librosa.load(path, sr=SR, mono=True)
            f0 = librosa.yin(
                audio, fmin=F0_MIN, fmax=F0_MAX,
                sr=SR, frame_length=FRAME_LENGTH, hop_length=HOP,
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

    # ==================== 相似度 ====================
    @staticmethod
    def _coarse(ref, q):
        """向量化滑窗余弦：返回 (最高分, 起始帧号)"""
        r = ref.astype(np.float64)
        qq = q.astype(np.float64)
        q_norm = float(np.linalg.norm(qq)) + 1e-8
        num = np.correlate(r, qq, mode="valid")
        cum = np.concatenate(([0.0], np.cumsum(r ** 2)))
        denom = np.sqrt(np.maximum(cum[q.size:] - cum[:-q.size], 0.0)) * q_norm + 1e-8
        scores = num / denom
        best = int(np.argmax(scores))
        return float(scores[best]), best

    def match(self, hum_wav):
        """返回 (song_title, offset_sec, score, second_score, margin)"""
        self._load_refs()
        with self._lock:
            refs = dict(self._refs)
        if not refs:
            return None, 0.0, 0.0, 0.0, 0.0
        q = self._extract_midi(hum_wav) if hum_wav else None
        if q is None or q.size < 3:
            return None, 0.0, 0.0, 0.0, 0.0

        cands = []
        for title, ref in refs.items():
            if ref.size < q.size:
                continue
            score, idx = self._coarse(ref, q)
            cands.append((score, title, idx))
        if not cands:
            return None, 0.0, 0.0, 0.0, 0.0
        cands.sort(key=lambda item: -item[0])

        best_score, best_title, best_idx = cands[0]
        second_score = cands[1][0] if len(cands) > 1 else 0.0
        return best_title, best_idx * HOP / SR, best_score, second_score, best_score - second_score
