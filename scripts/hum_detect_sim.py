# -*- coding: utf-8 -*-
"""
hum_detect_sim.py —— 独立哼唱检测 + 歌曲匹配模拟脚本（不依赖项目模块，也不需要 librosa）

定位：
    项目的哼唱链路是「VAD 分段 → pyin 判定 → yin 音高序列 → 曲库滑窗余弦」。
    本脚本用 numpy 复刻同一套算法，用于**离线跑分**和现场调参，不参与线上逻辑。

为什么不用 librosa：
    librosa.pyin / librosa.yin 走 numba JIT，本机首次调用要编译几十秒到几分钟，
    看上去像"脚本卡死"。这里改成等价的 numpy YIN（FFT 自相关 + CMNDF + 抛物线插值），
    行为与 librosa 一致：yin 不做清浊判定（静音帧也会给出音高），pyin 才有。

两种用法：
    1) 离线跑分（推荐，可复现）：
        runtime\\python.exe scripts\\hum_detect_sim.py --wav sing.m4a --truth "Letter Song"
        runtime\\python.exe scripts\\hum_detect_sim.py --wav sing.m4a 星降落海.m4a --step 1
    2) 实时麦克风（原来那种）：
        runtime\\python.exe scripts\\hum_detect_sim.py

参数优先级：命令行 > config.yml（sensevoice.* / meowsongs.pass_the_baton.*）> 脚本常量。
"""

import argparse
import os
import re
import sys
import time
from collections import deque

import numpy as np

# ==================== 路径与默认参数 ====================
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEOW_DIR = os.path.join(ROOT, "character", "songs", "meow_list")
CONFIG_PATH = os.path.join(ROOT, "config.yml")

SAMPLE_RATE = 16000            # 固定 16k（与项目一致）
CHUNK_MS = 300                 # 实时模式每帧时长（镜像 audio.chunk_size_ms）
ENERGY_THRESHOLD = 300         # VAD 能量阈值（镜像 sensevoice.vad_energy_threshold）
SILENCE_THRESHOLD = 2.0        # 段结束静音（镜像 sensevoice.silence_threshold）
HUM_COLLECT_SEC = 7.0          # 判定窗口（镜像 meowsongs.pass_the_baton.hum_collect_sec）

F0_MIN = 65.0                  # 判定用最低基频（镜像 hum_detect.F0_MIN）
F0_MAX = 800.0                 # 判定用最高基频
JUDGE_FRAME_LENGTH = 1024      # 判定帧长（镜像 hum_detect.JUDGE_FRAME_LENGTH）
JUDGE_HOP = 1024               # 判定帧移（镜像 hum_detect.JUDGE_HOP）

MATCH_F0_MIN = 80.0            # 匹配用最低基频（镜像 hum_match.F0_MIN）
MATCH_FRAME_LENGTH = 2048      # 匹配帧长（镜像 hum_match.FRAME_LENGTH）
MATCH_HOP = 256                # 匹配帧移（镜像 hum_match.HOP）→ 16 ms/帧

F0_VOICED_RATIO = 0.55         # 镜像 meowsongs.pass_the_baton.f0_voiced_ratio
F0_STABLE_RATIO = 0.6          # 镜像 f0_stable_ratio
F0_STABLE_HALF_STEP = 0.5      # 镜像 f0_stable_half_step
F0_UNIQUE_NOTES = 3            # 镜像 f0_unique_notes

MATCH_THRESHOLD = 0.35         # 镜像 match_threshold
MIN_MARGIN = 0.04              # 镜像 min_margin

# yin 的"有声"近似：CMNDF 谷值置信度 >= 该值算有声（pyin 用 voiced_prob，这里取等效阈值）
VOICED_CONF = 0.70
# ====================================================


def _ts():
    return time.strftime("%H:%M:%S")


# ==================== 配置读取 ====================
def load_config_overrides():
    """从 config.yml 读阈值/能量等，让脚本与线上永远一致（读不到就保持脚本常量）"""
    out = {}
    try:
        import yaml
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return out
    sv = cfg.get("sensevoice") or {}
    audio = cfg.get("audio") or {}
    ms = ((cfg.get("meowsongs") or {}).get("pass_the_baton")) or {}
    if isinstance(ms, dict):
        mapping = {
            "energy": sv.get("vad_energy_threshold"),
            "silence": sv.get("silence_threshold"),
            "chunk_ms": audio.get("chunk_size_ms"),
            "collect": ms.get("hum_collect_sec"),
            "voiced_ratio": ms.get("f0_voiced_ratio"),
            "stable_ratio": ms.get("f0_stable_ratio"),
            "half_step": ms.get("f0_stable_half_step"),
            "unique_notes": ms.get("f0_unique_notes"),
            "match_threshold": ms.get("match_threshold"),
            "min_margin": ms.get("min_margin"),
        }
        for k, v in mapping.items():
            if v is not None:
                out[k] = v
    return out


# ==================== 音高提取（numpy YIN，等价 librosa） ====================
def yin(y, frame_length=MATCH_FRAME_LENGTH, hop_length=MATCH_HOP,
        fmin=MATCH_F0_MIN, fmax=F0_MAX, trough_threshold=0.12):
    """numpy YIN：返回 (f0 Hz, 每帧置信度 0~1)

    与 librosa.yin 一致：**不做清浊判定**，静音帧也会返回音高（这也是项目匹配侧
    会被静音毒帧污染的根源，见 --mask 选项）。
    """
    y = np.asarray(y, dtype=np.float64)
    maxlag = int(np.ceil(SAMPLE_RATE / fmin))
    minlag = max(2, int(np.floor(SAMPLE_RATE / fmax)))
    n = y.size
    n_frames = 1 + max(0, n - frame_length) // hop_length
    f0 = np.full(n_frames, np.nan, dtype=np.float64)
    conf = np.zeros(n_frames, dtype=np.float64)
    if n_frames <= 0:
        return f0, conf

    nfft = 1 << int(np.ceil(np.log2(frame_length + maxlag + 1)))
    for i in range(n_frames):
        x = y[i * hop_length: i * hop_length + frame_length]
        if x.size < frame_length:
            break
        spec = np.fft.rfft(x, nfft)
        ac = np.fft.irfft(spec * np.conj(spec), nfft)[:maxlag + 1]
        esuf = np.cumsum((x ** 2)[::-1])[::-1]          # 后缀能量 e(τ)=Σ_{j≥τ} x²
        d = esuf[0] + esuf[:maxlag + 1] - 2 * ac       # 差分函数
        d[0] = 0.0
        cm = np.ones_like(d)
        cum = np.cumsum(d[1:])
        cm[1:] = d[1:] * np.arange(1, len(d)) / np.maximum(cum, 1e-12)
        lo, hi = minlag, min(maxlag, len(cm) - 1)
        if hi <= lo:
            continue
        seg = cm[lo:hi + 1]
        below = np.where(seg < trough_threshold)[0]
        k = lo + (int(below[0]) if below.size else int(np.argmin(seg)))
        if 0 < k < len(cm) - 1:
            a, b, c = cm[k - 1], cm[k], cm[k + 1]
            den = a - 2 * b + c
            kk = k + (0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0)
        else:
            kk = float(k)
        if kk > 1:
            f0[i] = SAMPLE_RATE / kk
            conf[i] = 1.0 - cm[k]
    return f0, conf


def _midi(f0):
    out = np.full(len(f0), np.nan, dtype=np.float64)
    ok = np.isfinite(f0) & (f0 > 0)
    out[ok] = 12.0 * np.log2(f0[ok] / 440.0) + 69.0
    return out


def _frame_energy(y, frame_length, hop_length):
    """与 yin 对齐的逐帧 RMS（int16 刻度），用于 --mask"""
    n = y.size
    n_frames = 1 + max(0, n - frame_length) // hop_length
    e = np.zeros(max(0, n_frames), dtype=np.float64)
    for i in range(e.size):
        x = y[i * hop_length: i * hop_length + frame_length]
        if x.size == 0:
            break
        e[i] = float(np.sqrt(np.mean(x ** 2)))
    return e


# ==================== 判定（镜像 hum_detect._analyze_buffer） ====================
def judge(audio):
    """返回 (ok, metrics)：三项指标同时满足才算哼唱"""
    f0, conf = yin(audio, frame_length=JUDGE_FRAME_LENGTH, hop_length=JUDGE_HOP,
                   fmin=F0_MIN, fmax=F0_MAX)
    voiced = np.isfinite(f0) & (conf >= VOICED_CONF)
    idx = np.where(voiced)[0]
    m = {
        "voiced_frames": int(voiced.sum()),
        "total_frames": int(f0.size),
        "ratio": 0.0,
        "stable_ratio": 0.0,
        "unique_notes": 0,
        "voiced_ratio_trim": 0.0,
    }
    if idx.size < 3:
        return False, m
    midi = _midi(f0)[voiced]
    diff = np.abs(np.diff(midi))
    m["ratio"] = float(voiced.mean())
    m["voiced_ratio_trim"] = float(voiced[idx[0]:idx[-1] + 1].mean())
    m["stable_ratio"] = float(np.mean(diff < F0_STABLE_HALF_STEP)) if diff.size else 0.0
    m["unique_notes"] = int(len(np.unique(np.round(midi).astype(int))))
    ok = (m["ratio"] >= F0_VOICED_RATIO
          and m["stable_ratio"] >= F0_STABLE_RATIO
          and m["unique_notes"] >= F0_UNIQUE_NOTES)
    return ok, m


# ==================== 匹配特征（镜像 hum_match._extract_midi） ====================
def extract_match_midi(audio, use_mask=False):
    """去均值 midi 序列；use_mask=True 时先丢掉低能量帧（项目现状是不丢的）"""
    f0, _ = yin(audio, frame_length=MATCH_FRAME_LENGTH, hop_length=MATCH_HOP, fmin=MATCH_F0_MIN)
    ok = np.isfinite(f0)
    if use_mask:
        e = _frame_energy(audio, MATCH_FRAME_LENGTH, MATCH_HOP)
        ok = ok & (e >= max(ENERGY_THRESHOLD * 0.5, 1.0))
    valid = f0[ok]
    if valid.size < 3:
        return None
    midi = 12.0 * np.log2(valid / 440.0) + 69.0
    return (midi - np.mean(midi)).astype(np.float64)


# ==================== 曲库 ====================
def load_refs(verbose=True):
    """加载曲库全部 *_pitch.npy（16 ms/帧的去均值半音序列）"""
    refs = {}
    if not os.path.isdir(MEOW_DIR):
        print(f"!! 曲库目录不存在: {MEOW_DIR}")
        return refs
    for name in sorted(os.listdir(MEOW_DIR)):
        npy = os.path.join(MEOW_DIR, name, f"{name}_pitch.npy")
        if not os.path.exists(npy):
            continue
        try:
            refs[name] = np.load(npy).astype(np.float64)
        except Exception as exc:
            if verbose:
                print(f"!! 读取失败 {name}: {exc}")
    if verbose:
        print(f"曲库: {len(refs)} 首（{MEOW_DIR}）")
        if not refs:
            print("   警告：曲库为空，匹配不可能命中")
    return refs


def match_song(refs, query, topn=5):
    """滑窗余弦：返回 (best, score, offset_sec, second, margin, top列表)"""
    if not refs or query is None or query.size < 3:
        return None, 0.0, 0.0, 0.0, 0.0, []
    qn = float(np.linalg.norm(query)) + 1e-8
    scored = []
    for title, ref in refs.items():
        if ref.size < query.size:
            continue
        num = np.correlate(ref, query, mode="valid")
        cum = np.concatenate(([0.0], np.cumsum(ref ** 2)))
        den = np.sqrt(np.maximum(cum[query.size:] - cum[:-query.size], 0.0)) * qn + 1e-8
        scores = num / den
        idx = int(np.argmax(scores))
        scored.append((float(scores[idx]), title, idx * MATCH_HOP / SAMPLE_RATE))
    if not scored:
        return None, 0.0, 0.0, 0.0, 0.0, []
    scored.sort(key=lambda z: -z[0])
    second = scored[1][0] if len(scored) > 1 else 0.0
    best, title, off = scored[0]
    return title, best, off, second, best - second, scored[:topn]


# ==================== 歌词 ====================
def _read_text(path):
    for enc in ("utf-8", "gbk", "utf-8-sig"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


TIME_RE = re.compile(r"\[(\d{1,3}):(\d{2}(?:[.:]\d{1,3})?)\](.*)")


def load_lrc(title):
    """解析 {title}.lrc → [(秒, 歌词)]，按时间升序"""
    path = os.path.join(MEOW_DIR, title, f"{title}.lrc")
    if not os.path.exists(path):
        return []
    items = []
    for line in _read_text(path).splitlines():
        m = TIME_RE.match(line.strip())
        if not m:
            continue
        frac = m.group(2).replace(":", ".")
        sec = int(m.group(1)) * 60 + float(frac)
        text = m.group(3).strip()
        if text:
            items.append((sec, text))
    items.sort(key=lambda x: x[0])
    return items


def find_lyric_start(title, sec):
    """找 sec 之后（含 0.05 s 容差）最近的一句；都没有则取最后一句"""
    items = load_lrc(title)
    if not items:
        return None
    for t, text in items:
        if t >= sec - 0.05:
            return t, text
    return items[-1]


# ==================== 实时模式（麦克风） ====================
class HumDetector:
    """实时流式复刻：VAD 分段 → 满 collect 秒判定 → 段结束定位接唱点"""

    def __init__(self, refs, use_mask=False):
        self.refs = refs
        self.use_mask = use_mask
        self.buffer = deque()
        self.buf_samples = 0
        self.buf_seconds = 0.0
        self.speech_start = 0.0
        self.last_sound = 0.0
        self._last_progress = 0.0
        self.checked = False
        self.triggered = False
        self.locked = None          # (title, offset, score)

    def feed(self, arr):
        rms = float(np.sqrt(np.mean(arr ** 2)))
        now = time.time()

        if rms >= ENERGY_THRESHOLD:
            if self.speech_start == 0.0:
                self.speech_start = now
                self._last_progress = now
                print(f"[{_ts()}] 语音段开始")
            self.last_sound = now
        elif self.speech_start > 0.0 and now - self.last_sound >= SILENCE_THRESHOLD:
            self._finish()
            self.speech_start = 0.0
            self.last_sound = 0.0
            self.buffer.clear()
            self.buf_samples = 0
            self.buf_seconds = 0.0
            self.checked = False
            self.triggered = False
            self.locked = None

        if self.speech_start > 0.0:
            self.buffer.append(arr)
            self.buf_samples += arr.size
            self.buf_seconds = self.buf_samples / SAMPLE_RATE
            if now - self._last_progress >= 1.0:
                self._last_progress = now
                print(f"[{_ts()}]   ... 已累积 {self.buf_seconds:.1f}s")
            if not self.checked and self.buf_seconds >= HUM_COLLECT_SEC:
                self.checked = True
                self._lock_at_collect()

    def _lock_at_collect(self):
        audio = np.concatenate(list(self.buffer))
        ok, m = judge(audio)
        print(f"[{_ts()}] 满 {HUM_COLLECT_SEC:g}s 判定（实际 {self.buf_seconds:.2f}s）")
        print_metrics(m)
        if not ok:
            print("        判定：非哼唱 → 段结束用完整音频兜底")
            return
        self.triggered = True
        q = extract_match_midi(audio, self.use_mask)
        title, score, off, second, margin, top = match_song(self.refs, q)
        print(f"        匹配 top{len(top)}: " + ", ".join(f"{t[:12]}:{s:.3f}" for s, t, _ in top))
        if title and score >= MATCH_THRESHOLD and margin >= MIN_MARGIN:
            self.locked = (title, off, score)
            print(f"        定歌：《{title}》 score={score:.3f} 分差={margin:.3f} offset={off:.1f}s")
        else:
            print(f"        未锁定：{title} score={score:.3f} 分差={margin:.3f}"
                  f"（阈值 {MATCH_THRESHOLD}/{MIN_MARGIN}）")

    def _finish(self):
        if self.buf_seconds < HUM_COLLECT_SEC:
            print(f"[{_ts()}] 段结束，时长 {self.buf_seconds:.2f}s < {HUM_COLLECT_SEC:g}s，丢弃")
            return
        T = self.buf_seconds
        print(f"[{_ts()}] 段结束（哼唱时长 T={T:.2f}s）")
        audio = np.concatenate(list(self.buffer))
        if self.locked:
            title, off, score = self.locked
        else:
            ok, m = judge(audio)
            print_metrics(m)
            if not ok:
                print("        判定：非哼唱")
                return
            q = extract_match_midi(audio, self.use_mask)
            title, score, off, second, margin, top = match_song(self.refs, q)
            if not title or score < MATCH_THRESHOLD or margin < MIN_MARGIN:
                print(f"        未定歌：{title} score={score:.3f} 分差={margin:.3f}")
                return
        pos = off + T
        lyric = find_lyric_start(title, pos)
        print(f"        接唱点 = offset({off:.1f}s) + T({T:.2f}s) = {pos:.1f}s")
        if lyric:
            t, text = lyric
            print(f"        → 《{title}》[{int(t // 60):02d}:{t % 60:05.2f}] \"{text}\" 开始接唱")
        else:
            print(f"        → 《{title}》无歌词，从 {pos:.1f}s 播放")

    @staticmethod
    def _fmt(sec):
        return f"{int(sec // 60):02d}:{sec % 60:05.2f}"


def print_metrics(m):
    def mark(cond):
        return "OK" if cond else "!!"
    print(f"        voiced_ratio = {m['ratio']:.3f} (阈值 {F0_VOICED_RATIO}) {mark(m['ratio'] >= F0_VOICED_RATIO)}"
          f"   首尾裁剪后 = {m['voiced_ratio_trim']:.3f}")
    print(f"        stable_ratio = {m['stable_ratio']:.3f} (阈值 {F0_STABLE_RATIO}) {mark(m['stable_ratio'] >= F0_STABLE_RATIO)}")
    print(f"        unique_notes = {m['unique_notes']} (阈值 {F0_UNIQUE_NOTES}) {mark(m['unique_notes'] >= F0_UNIQUE_NOTES)}")
    print(f"        voiced_frames = {m['voiced_frames']} / {m['total_frames']}")


# ==================== 离线模式（wav 跑分） ====================
def _load_wav(path):
    """读 wav/m4a/mp3 → 16k 单声道 float32（int16 刻度）；m4a 走 ffmpeg 兜底"""
    try:
        import soundfile as sf
        y, sr = sf.read(path, dtype="float32", always_2d=False)
        if y.ndim > 1:
            y = y.mean(axis=1)
        y = y * 32768.0
        if sr != SAMPLE_RATE:
            from math import gcd
            from scipy.signal import resample_poly
            g = gcd(sr, SAMPLE_RATE)
            y = resample_poly(y, SAMPLE_RATE // g, sr // g)
        return y.astype(np.float64)
    except Exception:
        import subprocess
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), f"hum_sim_{os.getpid()}.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-ac", "1",
                        "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", tmp], check=True)
        import soundfile as sf
        y, _ = sf.read(tmp, dtype="int16")
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return y.astype(np.float64)


def _active_span(y):
    """按能量阈值找首尾有声帧，返回 (起, 止) 秒；找不到返回 (0, 时长)"""
    chunk = int(SAMPLE_RATE * CHUNK_MS / 1000)
    n = len(y) // chunk
    if n <= 0:
        return 0.0, len(y) / SAMPLE_RATE
    rms = np.array([np.sqrt(np.mean(y[i * chunk:(i + 1) * chunk] ** 2)) for i in range(n)])
    idx = np.where(rms >= ENERGY_THRESHOLD)[0]
    if idx.size == 0:
        return 0.0, len(y) / SAMPLE_RATE
    return idx[0] * CHUNK_MS / 1000.0, (idx[-1] + 1) * CHUNK_MS / 1000.0


def run_offline(paths, truth, step, win, use_mask):
    refs = load_refs()
    if not refs:
        return 1
    print()
    for path in paths:
        if not os.path.exists(path):
            print(f"!! 文件不存在: {path}")
            continue
        y = _load_wav(path)
        dur = len(y) / SAMPLE_RATE
        a, b = _active_span(y)
        print("=" * 78)
        print(f"文件: {os.path.basename(path)}  时长 {dur:.2f}s  有声区间 {a:.2f}~{b:.2f}s "
              f"({b - a:.2f}s)  峰值 {np.abs(y).max() / 32768:.3f}")
        span = b - a
        if span < win:
            print(f"  有声部分只有 {span:.2f}s < 窗口 {win:g}s，无法切出完整窗口")
            continue

        hits = 0
        total = 0
        t = a
        print(f"{'窗口':>14}{'判定':>8}{'top1':>18}{'分数':>8}{'分差':>8}{'排名':>6}   top3")
        while t + win <= b + 1e-6:
            seg = y[int(t * SAMPLE_RATE): int((t + win) * SAMPLE_RATE)]
            ok, m = judge(seg)
            q = extract_match_midi(seg, use_mask)
            title, score, off, second, margin, top = match_song(refs, q, topn=3)
            rank = "-"
            if truth:
                for i, (s, tt, _) in enumerate(top):
                    if tt == truth:
                        rank = str(i + 1)
                # top3 里没有就再单独算一遍真实排名
                if rank == "-":
                    full = match_song(refs, q, topn=len(refs))[5]
                    for i, (s, tt, _) in enumerate(full):
                        if tt == truth:
                            rank = str(i + 1)
                            break
                total += 1
                if title == truth:
                    hits += 1
            print(f"{t:8.2f}~{t + win:<5.2f}{'哼唱' if ok else '非哼唱':>8}"
                  f"{str(title)[:16]:>18}{score:8.3f}{margin:8.3f}{rank:>6}   "
                  + ", ".join(f"{tt[:10]}:{s:.3f}" for s, tt, _ in top))
            print(f"{'':>14}指标 voiced={m['ratio']:.3f} stable={m['stable_ratio']:.3f} "
                  f"notes={m['unique_notes']}")
            t += step
        if truth and total:
            print(f"  → 真值《{truth}》命中 {hits}/{total}（窗口 {win:g}s / 步长 {step:g}s）")
    return 0


# ==================== 实时模式入口 ====================
def run_live(device_index, use_mask):
    refs = load_refs()
    if not refs:
        return 1
    try:
        import pyaudio
    except ImportError:
        print("缺少 pyaudio，无法实时模式；可用 --wav 离线跑分")
        return 1
    chunk = int(SAMPLE_RATE * CHUNK_MS / 1000)
    pa = pyaudio.PyAudio()
    try:
        info = pa.get_default_input_device_info()
        print(f"默认麦克风: {info['name']} (设备采样率 {int(info['defaultSampleRate'])}Hz)")
    except Exception:
        pass
    try:
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
                         input=True, frames_per_buffer=chunk,
                         input_device_index=(device_index if device_index >= 0 else None))
    except Exception as exc:
        print(f"打开麦克风失败: {exc}")
        pa.terminate()
        return 1

    print(f"\n开始监听（帧 {CHUNK_MS}ms / 能量阈值 {ENERGY_THRESHOLD:g} / "
          f"窗口 {HUM_COLLECT_SEC:g}s）。Ctrl+C 退出。\n")
    det = HumDetector(refs, use_mask)
    try:
        while True:
            data = stream.read(chunk, exception_on_overflow=False)
            det.feed(np.frombuffer(data, dtype=np.int16).astype(np.float64))
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
    return 0


# ==================== main ====================
def apply_overrides(cfg, args):
    """命令行 > config.yml > 脚本常量"""
    global ENERGY_THRESHOLD, SILENCE_THRESHOLD, HUM_COLLECT_SEC, CHUNK_MS
    global F0_VOICED_RATIO, F0_STABLE_RATIO, F0_STABLE_HALF_STEP, F0_UNIQUE_NOTES
    global MATCH_THRESHOLD, MIN_MARGIN
    for key, attr in (("energy", "ENERGY_THRESHOLD"), ("silence", "SILENCE_THRESHOLD"),
                      ("chunk_ms", "CHUNK_MS"), ("collect", "HUM_COLLECT_SEC"),
                      ("voiced_ratio", "F0_VOICED_RATIO"), ("stable_ratio", "F0_STABLE_RATIO"),
                      ("half_step", "F0_STABLE_HALF_STEP"), ("unique_notes", "F0_UNIQUE_NOTES"),
                      ("match_threshold", "MATCH_THRESHOLD"), ("min_margin", "MIN_MARGIN")):
        if key in cfg:
            globals()[attr] = cfg[key]
    if args.energy is not None:
        ENERGY_THRESHOLD = args.energy
    if args.silence is not None:
        SILENCE_THRESHOLD = args.silence
    if args.collect is not None:
        HUM_COLLECT_SEC = args.collect
    if args.match_threshold is not None:
        MATCH_THRESHOLD = args.match_threshold
    if args.min_margin is not None:
        MIN_MARGIN = args.min_margin


def main():
    ap = argparse.ArgumentParser(description="哼唱检测 + 定歌模拟（离线跑分 / 实时麦克风）")
    ap.add_argument("--wav", nargs="+", default=None, help="离线跑分：音频文件（可多个）")
    ap.add_argument("--truth", default=None, help="离线跑分：正确歌名（用于统计命中率）")
    ap.add_argument("--step", type=float, default=1.0, help="离线滑窗步长（秒），默认 1")
    ap.add_argument("--win", type=float, default=None, help="离线窗口长度（秒），默认取 collect")
    ap.add_argument("--mask", action="store_true", help="匹配特征先按能量丢掉低能量帧（对照用）")
    ap.add_argument("--device-index", type=int, default=-1, help="实时模式麦克风设备号")
    ap.add_argument("--energy", type=float, default=None, help="覆盖 VAD 能量阈值")
    ap.add_argument("--silence", type=float, default=None, help="覆盖段结束静音秒数")
    ap.add_argument("--collect", type=float, default=None, help="覆盖判定窗口秒数")
    ap.add_argument("--match-threshold", type=float, default=None)
    ap.add_argument("--min-margin", type=float, default=None)
    args = ap.parse_args()

    apply_overrides(load_config_overrides(), args)
    win = args.win if args.win else HUM_COLLECT_SEC

    print("=" * 78)
    print("哼唱检测 + 定歌模拟（与项目同算法，numpy 实现，不依赖 librosa）")
    print("=" * 78)
    print(f"采样率 {SAMPLE_RATE} / 实时帧 {CHUNK_MS}ms / VAD 能量 {ENERGY_THRESHOLD:g} / "
          f"静音分段 {SILENCE_THRESHOLD:g}s")
    print(f"判定窗口 {HUM_COLLECT_SEC:g}s / pyin 等效帧长 {JUDGE_FRAME_LENGTH} 帧移 {JUDGE_HOP} "
          f"/ 匹配帧长 {MATCH_FRAME_LENGTH} 帧移 {MATCH_HOP}")
    print(f"判定阈值 voiced={F0_VOICED_RATIO} stable={F0_STABLE_RATIO}(half_step={F0_STABLE_HALF_STEP}) "
          f"notes={F0_UNIQUE_NOTES}")
    print(f"定歌阈值 score>={MATCH_THRESHOLD} 分差>={MIN_MARGIN}")
    if args.mask:
        print("匹配特征：已开启能量掩码（与项目现状不同，仅对照）")
    print("=" * 78)

    if args.wav:
        return run_offline(args.wav, args.truth, args.step, win, args.mask)
    return run_live(args.device_index, args.mask)


if __name__ == "__main__":
    sys.exit(main())
