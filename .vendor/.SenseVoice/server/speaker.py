# -*- coding: utf-8 -*-
# server/speaker.py - 声纹识别：CAM++ 嵌入抽取 + 声纹库余弦匹配

import json
import os
import time

import numpy as np
import torch
from scipy.spatial.distance import cosine

from audio import save_audio_to_wav


class SpeakerVerification:
    """声纹验证管理器：提取说话人嵌入并与 speaker_db 比对"""

    def __init__(self, model, db_path: str, reload_sec: int, threshold: float):
        self.model = model
        self.db_path = db_path
        self.reload_sec = reload_sec
        self.threshold = threshold
        self._cache = {}
        self._cache_ts = 0.0

    def _load_db(self) -> dict:
        """读取声纹数据库 JSON"""
        if not os.path.exists(self.db_path):
            return {}
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _get_db_cached(self) -> dict:
        """按刷新周期获取声纹库缓存"""
        now = time.time()
        if now - self._cache_ts >= self.reload_sec:
            self._cache = self._load_db()
            self._cache_ts = now
        return self._cache

    def extract_embedding(self, audio_bytes: bytes):
        """抽取单段音频的说话人嵌入向量"""
        tmp_path = None
        try:
            tmp_path = save_audio_to_wav(audio_bytes)
            result = self.model.generate(input=tmp_path, embedding=True)
            if result and len(result) > 0:
                emb = result[0].get("spk_embedding")
                if emb is not None:
                    if torch.is_tensor(emb):
                        emb = emb.cpu().numpy()
                    if emb.ndim == 2 and emb.shape[0] == 1:
                        emb = emb[0]
                    elif emb.ndim > 2:
                        emb = emb.flatten()
                    if emb.ndim != 1:
                        raise ValueError(f"无法转换为1维向量，形状: {emb.shape}")
                    return emb.astype(np.float32)
            return None
        except Exception as e:
            print(f"声纹提取失败: {e}")
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def verify(self, audio_bytes: bytes) -> tuple:
        """与声纹库比对，返回 (speaker_name, score)"""
        emb = self.extract_embedding(audio_bytes)
        if emb is None:
            return "unknown", 0.0
        best_name, best_score = "unknown", 0.0
        for name, ref in self._get_db_cached().items():
            if ref is None:
                continue
            ref_arr = np.array(ref, dtype=np.float32)
            sim = 1.0 - cosine(emb, ref_arr)
            print(f"声纹相似度 [{name}]: {sim:.4f}")
            if sim > best_score and sim > self.threshold:
                best_score, best_name = sim, name
        return best_name, float(best_score)

    def register_speaker(self, name: str, audio_bytes: bytes) -> bool:
        """注册或覆盖说话人声纹"""
        emb = self.extract_embedding(audio_bytes)
        if emb is None:
            return False
        db = self._load_db()
        db[name] = emb.tolist()
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            self._cache_ts = 0.0
            return True
        except Exception as e:
            print(f"保存声纹数据库失败: {e}")
            return False
