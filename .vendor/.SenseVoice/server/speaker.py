# -*- coding: utf-8 -*-
# server/speaker.py - 声纹识别：CAM++ 嵌入抽取 + 声纹库余弦匹配（说话/哼唱双模板）

import json
import os
import time

import numpy as np
import torch
from scipy.spatial.distance import cosine

from audio import save_audio_to_wav

DEFAULT_THRESHOLD_SPEECH = 0.2
DEFAULT_THRESHOLD_SING = 0.6


class SpeakerVerification:
    """声纹验证管理器：提取说话人嵌入并与 speaker_db 比对。

    声纹库兼容两种条目格式：
        旧：{"000001": [192 floats]}                          → 视为 speech 模板
        新：{"000001": {"speech": [...], "sing": [...]}}       → 说话/哼唱分域
    """

    def __init__(self, model, db_path: str, reload_sec: int, threshold: float,
                 threshold_sing: float = DEFAULT_THRESHOLD_SING):
        self.model = model
        self.db_path = db_path
        self.reload_sec = reload_sec
        self.threshold = threshold
        self.threshold_sing = threshold_sing
        self._cache = {}
        self._cache_ts = 0.0

    # ==================== 声纹库读写 ====================
    def _load_db_raw(self) -> dict:
        """读取声纹数据库 JSON 原始内容"""
        if not os.path.exists(self.db_path):
            return {}
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _norm_vec(value):
        """把一条向量归一化成 L2=1 的 ndarray，无效返回 None"""
        if value is None:
            return None
        arr = np.asarray(value, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return None
        norm = float(np.linalg.norm(arr))
        return arr / norm if norm > 1e-8 else arr

    @classmethod
    def _norm_entry(cls, raw) -> dict:
        """单条声纹归一化：list → speech 模板；dict → speech / sing 两域"""
        if isinstance(raw, dict):
            return {
                "speech": cls._norm_vec(raw.get("speech")),
                "sing": cls._norm_vec(raw.get("sing")),
            }
        return {"speech": cls._norm_vec(raw), "sing": None}

    def _load_db(self) -> dict:
        """读取声纹数据库并归一化为 {name: {speech, sing}}"""
        return {name: self._norm_entry(raw) for name, raw in self._load_db_raw().items()}

    def _get_db_cached(self) -> dict:
        """按刷新周期获取声纹库缓存"""
        now = time.time()
        if now - self._cache_ts >= self.reload_sec:
            self._cache = self._load_db()
            self._cache_ts = now
        return self._cache

    # ==================== 嵌入抽取 ====================
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

    # ==================== 验证 ====================
    def verify(self, audio_bytes: bytes, hum: bool = False,
               thr_speech: float = None, thr_sing: float = None) -> tuple:
        """与声纹库比对，返回 (speaker_name, score, template)

        - hum=False（普通说话）：只比说话模板，走原逻辑；
        - hum=True（判为哼唱）：只比哼唱模板；该身份没录哼唱模板时才回落到说话模板，
          不因"哼唱分没过"而回落，否则别人的歌声会从说话道混进来。
        template ∈ {"sing", "speech", ""}
        """
        emb = self.extract_embedding(audio_bytes)
        if emb is None:
            return "unknown", 0.0, ""
        norm = float(np.linalg.norm(emb))
        if norm <= 1e-8:
            return "unknown", 0.0, ""
        emb = emb / norm

        thr_sp = self.threshold if thr_speech is None else float(thr_speech)
        thr_sg = self.threshold_sing if thr_sing is None else float(thr_sing)
        db = self._get_db_cached()
        lanes = ("sing",) if hum else ("speech",)

        for lane in lanes:
            best_name, best_score, best_tpl = "unknown", 0.0, ""
            for name, entry in db.items():
                ref = entry.get(lane)
                tpl = lane
                thr = thr_sg if lane == "sing" else thr_sp
                if ref is None:
                    # 只有哼唱句、且该身份没录哼唱模板时，才用说话模板兜底
                    if lane != "sing":
                        continue
                    ref = entry.get("speech")
                    tpl = "speech"
                    thr = thr_sp
                    if ref is None:
                        continue
                sim = 1.0 - cosine(emb, ref)
                print(f"声纹相似度 [{name}] {tpl}={sim:.4f} (阈值 {thr:g})")
                if sim > best_score and sim > thr:
                    best_score, best_name, best_tpl = sim, name, tpl
            if best_name != "unknown":
                return best_name, float(best_score), best_tpl
        return "unknown", 0.0, ""

    # ==================== 注册 ====================
    def register_speaker(self, name: str, audio_bytes: bytes, kind: str = "speech") -> bool:
        """注册或覆盖某个说话人的某一域模板（kind: speech / sing）"""
        emb = self.extract_embedding(audio_bytes)
        if emb is None:
            return False
        db = self._load_db_raw()
        raw = db.get(name)
        entry = raw if isinstance(raw, dict) else ({"speech": raw} if raw is not None else {})
        entry = dict(entry)
        entry["sing" if kind == "sing" else "speech"] = np.asarray(emb, dtype=np.float32).tolist()
        db[name] = entry
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            self._cache_ts = 0.0
            return True
        except Exception as e:
            print(f"保存声纹数据库失败: {e}")
            return False
