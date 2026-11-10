# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/vocal_squeeze.py
# 清唱静音压缩：只切掉超过阈值的长静音段，切口两侧保留呼吸间隔；切口表供字幕时间映射
import numpy as np

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.toolbox.meowsongs.config import TBMeowSongsConfig

FRAME_SEC = 0.02      # 分析帧长（秒）
HYSTERESIS_DB = 6.0   # 迟滞：进入人声要比静音阈值高 6dB，防止尾音/气声边缘抖动
BRIDGE_SEC = 0.12     # 桥接：短于该时长、且远低于人声的杂音不切断长空档
BRIDGE_REL_DB = 20.0  # 桥接电平上限：高于 ref 该分贝数的活跃段视为真实内容，不桥接
FADE_MS = 15          # 接缝淡变，切口落在静音里，只作保险
MIN_OUT_SEC = 0.2     # 压缩结果短于该值视为异常，回退原音频


@singleton
class TBVocalSqueeze:
    """清唱切片的静音压缩（无状态，供即兴哼唱与听歌识曲接龙共用）"""

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.config = TBMeowSongsConfig()

    def squeeze(self, audio, sr):
        """返回 (压缩后音频, cuts)；cuts=[(源起点秒, 源终点秒)] 升序且不重叠"""
        try:
            if audio is None or len(audio) == 0 or not self.config.sq_enabled:
                return audio, []
            sr = int(sr or 1)
            if not np.issubdtype(audio.dtype, np.floating):
                audio = audio.astype(np.float32)
            mono = audio.mean(axis=1) if audio.ndim > 1 else audio
            frame = max(1, int(sr * FRAME_SEC))
            db = self._frame_db(mono, frame)
            if db.size < 3:
                return audio, []

            # 静音判定：相对峰值电平 + 绝对下限，两者取更高（更保守）的那个
            ref = float(np.percentile(db, 95))
            thr = max(ref - float(self.config.sq_rel_db), float(self.config.sq_abs_db))
            silent = ~self._vad(db, thr)
            if not silent.any():
                return audio, []
            if silent.all():
                # 整段没人声：只留极短静音，避免播出一段死气
                return audio[: max(1, int(MIN_OUT_SEC * sr))], []

            runs = self._bridge(self._runs(silent), db, ref)
            total = len(audio) / float(sr)
            head_keep = max(0.0, float(self.config.sq_head_keep_sec))
            tail_keep = max(0.0, float(self.config.sq_tail_keep_sec))
            cuts = []

            # 片头/片尾：把超出的死气裁掉，只保留呼吸上限
            if runs[0][0] == 0:
                lead = runs[0][1] * FRAME_SEC
                if lead > head_keep:
                    cuts.append((0.0, lead - head_keep))
            if runs[-1][1] == len(db):
                tail_start = runs[-1][0] * FRAME_SEC + tail_keep
                if tail_start < total:
                    cuts.append((tail_start, total))

            # 段内静音：只有长于 min_gap_sec 才切，两侧各留呼吸，短换气原样保留
            min_gap = max(0.0, float(self.config.sq_min_gap_sec))
            for i, (a, b) in enumerate(runs):
                # 片头/片尾静音已按边界规则处理，不重复当段内间隔切
                if i == 0 and a == 0:
                    continue
                if i == len(runs) - 1 and b == len(db):
                    continue
                s, e = a * FRAME_SEC, min(b * FRAME_SEC, total)
                if e - s <= min_gap:
                    continue
                cut_s, cut_e = s + head_keep, e - tail_keep
                if cut_e - cut_s > 0.05:
                    cuts.append((cut_s, cut_e))

            cuts = self._merge(cuts, total)
            if not cuts:
                return audio, []
            out = self._cut(audio, sr, cuts)
            if out.size < int(MIN_OUT_SEC * sr):
                return audio, []
            return out, cuts
        except Exception:
            self.log.exception("[VocalSqueeze] 静音压缩异常，按原音频播放")
            return audio, []

    def map_time(self, t, cuts):
        """把源时间轴上的 t 映射到压缩后的时间轴（落在切口内则映射到接缝）"""
        shift = 0.0
        for a, b in cuts:
            if t <= a:
                break
            if t < b:
                return a - shift
            shift += b - a
        return t - shift

    def map_lyrics(self, lines, base_sec, cuts):
        """把切片内歌词的绝对时间映射为相对播放起点的压缩后时间（单调不减）"""
        mapped = []
        prev = 0.0
        for item in lines:
            local = max(0.0, float(item.get("time", 0.0)) - float(base_sec))
            t = max(prev, self.map_time(local, cuts))
            mapped.append({"time": t, "text": item.get("text", "")})
            prev = t
        return mapped

    # ==================== 内部实现 ====================
    @staticmethod
    def _frame_db(mono, frame):
        """按帧算 RMS 电平（dBFS）"""
        n = mono.size // frame
        if n <= 0:
            return np.zeros(0, dtype=np.float32)
        x = mono[: n * frame].reshape(n, frame).astype(np.float32, copy=False)
        rms = np.sqrt(np.mean(x * x, axis=1) + 1e-12)
        return (20.0 * np.log10(rms + 1e-9)).astype(np.float32)

    @staticmethod
    def _vad(db, thr):
        """双阈值迟滞判人声：返回 True=有人声；刚开始若没有明显人声则按静音起步"""
        high = thr + HYSTERESIS_DB
        active = False
        mask = np.zeros(db.size, dtype=bool)
        for i in range(db.size):
            v = float(db[i])
            if active:
                if v < thr:
                    active = False
            elif v > high:
                active = True
            mask[i] = active
        return mask

    @staticmethod
    def _runs(mask):
        """连续 True 的帧区间 [start, end)"""
        out = []
        start = None
        for i, v in enumerate(mask):
            if v and start is None:
                start = i
            elif not v and start is not None:
                out.append((start, i))
                start = None
        if start is not None:
            out.append((start, len(mask)))
        return out

    @staticmethod
    def _bridge(runs, db, ref):
        """把夹在两个静音段之间、很短又很轻的杂音并进空档，避免爆音把长间奏劈成两段"""
        if len(runs) < 2:
            return runs
        bridge_frames = max(1, int(BRIDGE_SEC / FRAME_SEC))
        limit = ref - BRIDGE_REL_DB
        merged = [runs[0]]
        for a, b in runs[1:]:
            prev_a, prev_b = merged[-1]
            gap = a - prev_b
            if 0 < gap <= bridge_frames and float(np.max(db[prev_b:a])) < limit:
                merged[-1] = (prev_a, b)
            else:
                merged.append((a, b))
        return merged

    @staticmethod
    def _merge(cuts, total):
        """裁剪到 [0, total] 并合并重叠切口"""
        merged = []
        for a, b in sorted(cuts):
            a = max(0.0, min(a, total))
            b = max(0.0, min(b, total))
            if b - a <= 0.01:
                continue
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        return merged

    def _cut(self, audio, sr, cuts):
        """按切口表拼接保留区间，接缝处做短淡变"""
        fade = max(0, int(FADE_MS / 1000.0 * sr))
        parts = []
        pos = 0
        n = len(audio)
        for a, b in cuts:
            start = min(n, max(pos, int(round(a * sr))))
            end = min(n, int(round(b * sr)))
            if start > pos:
                seg = audio[pos:start].copy()
                if fade and seg.size > fade:
                    seg[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=seg.dtype)
                parts.append(seg)
            pos = max(pos, end)
        if pos < n:
            seg = audio[pos:].copy()
            if fade and seg.size > fade:
                seg[:fade] *= np.linspace(0.0, 1.0, fade, dtype=seg.dtype)
            parts.append(seg)
        if not parts:
            return audio[:0].copy()
        return np.concatenate(parts)
