# -*- coding: utf-8 -*-
"""
hum_detect_sim.py —— 独立哼唱检测 + 歌曲匹配模拟脚本（与项目算法完全一致，不依赖项目模块）

与项目对齐的算法：
    1. VAD 分段：能量阈值 + 连续静音分段（与 hum_detect 一致）；
    2. 满 HUM_COLLECT_SEC 秒立即判定（yin frame_length=1024，与 hum_detect 一致）；
    3. 判定通过后【不立即匹配】，继续累积，段结束时用【完整音频】匹配；
    4. 匹配前用 yin frame_length=2048 重新提取音高（与 hum_match 一致，两次提取）；
    5. QBH 滑动余弦匹配曲库 *_pitch.npy。

用法：
    runtime\\python.exe hum_detect_sim.py

依赖（仅第三方库，与项目解耦）：
    numpy / librosa / pyaudio

退出：
    Ctrl+C
"""

import os
import time
from collections import deque

import numpy as np

# ==================== 可调参数（微调这里） ====================
SAMPLE_RATE = 16000            # 采样率，固定 16k（与项目一致）
CHUNK_MS = 200                 # 每帧时长 ms（与 SenseVoice chunk_size_ms 一致）
CHUNK = int(SAMPLE_RATE * CHUNK_MS / 1000)

ENERGY_THRESHOLD = 400         # VAD 能量阈值（RMS，int16 幅度）。越大越不敏感
SILENCE_THRESHOLD = 2.0        # 段结束静音阈值（秒）。连续静音超过此值即分段

HUM_COLLECT_SEC = 7.0          # 哼唱最少累积时长（秒）。满此值立即判定

F0_MIN = 80                    # yin 最低基频（Hz）
F0_MAX = 800                   # yin 最高基频（Hz）
JUDGE_FRAME_LENGTH = 1024      # 判定用 yin 帧长（与项目 hum_detect 一致）
MATCH_FRAME_LENGTH = 2048      # 匹配用 yin 帧长（与项目 hum_match 一致）
HOP = 256                      # yin 帧移（与项目一致）

F0_VOICED_RATIO = 0.6          # 有声音高帧占比阈值（越高要求哼唱越连续）
F0_STABLE_RATIO = 0.6          # 稳定帧占比阈值（越高要求音高越稳）
F0_STABLE_HALF_STEP = 0.5      # 相邻帧音高差 < 此半音数视为稳定帧（越小越严）
F0_UNIQUE_NOTES = 3            # 唯一音符数阈值（越高要求旋律变化越多）

MEOW_DIR = os.path.join("character", "songs", "meow_list")  # 曲库目录
MATCH_THRESHOLD = 0.55         # QBH 匹配余弦相似度阈值

VERBOSE_FRAME = False          # True 时打印每帧能量（很刷屏，调试用）
# ============================================================


def _ts():
    return time.strftime("%H:%M:%S")


def _judge_metrics(f0):
    """根据 yin 输出的 f0（含 NaN）计算判定指标，返回 (ok, metrics)"""
    valid = f0[~np.isnan(f0)]
    metrics = {
        "voiced_frames": int(valid.size),
        "total_frames": int(f0.size),
        "ratio": 0.0,
        "stable_ratio": 0.0,
        "unique_notes": 0,
    }
    if valid.size < 3:
        return False, metrics

    ratio = valid.size / float(f0.size)
    midi = 12.0 * np.log2(valid / 440.0) + 69.0
    abs_diff = np.abs(np.diff(midi))
    stable_ratio = float(np.mean(abs_diff < F0_STABLE_HALF_STEP))
    unique_notes = len(np.unique(np.round(midi).astype(int)))

    ok = (
        ratio >= F0_VOICED_RATIO
        and stable_ratio >= F0_STABLE_RATIO
        and unique_notes >= F0_UNIQUE_NOTES
    )
    metrics.update({
        "ratio": ratio,
        "stable_ratio": stable_ratio,
        "unique_notes": unique_notes,
    })
    return ok, metrics


def judge(audio: np.ndarray):
    """判定：yin frame_length=1024（与项目 hum_detect 一致），返回 (ok, metrics)"""
    import librosa
    f0 = librosa.yin(
        audio.astype(np.float32) / 32768.0,
        fmin=F0_MIN, fmax=F0_MAX,
        sr=SAMPLE_RATE, frame_length=JUDGE_FRAME_LENGTH, hop_length=HOP,
    )
    return _judge_metrics(f0)


def extract_match_midi(audio: np.ndarray):
    """匹配音高：yin frame_length=2048（与项目 hum_match 一致），返回去均值 midi 序列"""
    import librosa
    f0 = librosa.yin(
        audio.astype(np.float32) / 32768.0,
        fmin=F0_MIN, fmax=F0_MAX,
        sr=SAMPLE_RATE, frame_length=MATCH_FRAME_LENGTH, hop_length=HOP,
    )
    valid = f0[~np.isnan(f0)]
    if valid.size < 3:
        return None
    midi = 12.0 * np.log2(valid / 440.0) + 69.0
    return (midi - np.mean(midi)).astype(np.float32)


def load_refs():
    """加载曲库全部 *_pitch.npy（yin 去均值半音序列，fl2048）"""
    refs = {}
    if not os.path.isdir(MEOW_DIR):
        return refs
    for name in sorted(os.listdir(MEOW_DIR)):
        d = os.path.join(MEOW_DIR, name)
        if not os.path.isdir(d):
            continue
        npy = os.path.join(d, f"{name}_pitch.npy")
        if os.path.exists(npy):
            try:
                refs[name] = np.load(npy)
            except Exception:
                pass
    return refs


def match_song(refs, query):
    """QBH 滑动窗口余弦相似度，返回 (命中歌名, 最高分, 偏移秒)。低于阈值返回 (None, 分, 偏移)"""
    if not refs or query is None or query.size < 3:
        return None, 0.0, 0.0

    q_norm = np.linalg.norm(query) + 1e-8
    best_title, best_score, best_offset = None, -1.0, 0.0
    for title, ref in refs.items():
        if ref.size < query.size:
            continue
        num = np.correlate(ref, query, mode="valid")
        c = np.concatenate(([0.0], np.cumsum(ref.astype(np.float64) ** 2)))
        window_sq = c[query.size:] - c[:-query.size]
        denom = np.sqrt(np.maximum(window_sq, 0.0)) * q_norm + 1e-8
        scores = num / denom
        i = int(np.argmax(scores))
        if scores[i] > best_score:
            best_title, best_score, best_offset = title, float(scores[i]), i * HOP / SAMPLE_RATE

    if best_score < MATCH_THRESHOLD:
        return None, best_score, best_offset
    return best_title, best_score, best_offset


class HumDetector:
    """复刻项目 hum_detect：VAD 分段 + 满 7 秒判定 + 段结束用完整音频匹配"""

    def __init__(self, refs):
        self.buffer = deque()
        self.buf_samples = 0
        self.buf_seconds = 0.0
        self.speech_start = 0.0
        self.last_sound = 0.0
        self._last_progress = 0.0
        self.checked_at_collect = False   # 满 7 秒是否已判过（无论成败）
        self.segment_triggered = False    # 本段是否已判定为哼唱
        self.refs = refs

    def feed(self, arr: np.ndarray):
        rms = float(np.sqrt(np.mean(arr ** 2)))
        now = time.time()

        if rms >= ENERGY_THRESHOLD:
            if self.speech_start == 0.0:
                self.speech_start = now
                self._last_progress = now
                print(f"[{_ts()}] 🔊 语音段开始")
            self.last_sound = now
        else:
            if self.speech_start > 0.0 and now - self.last_sound >= SILENCE_THRESHOLD:
                self._finish()
                self.speech_start = 0.0
                self.last_sound = 0.0
                self.buffer.clear()
                self.buf_samples = 0
                self.buf_seconds = 0.0
                self.checked_at_collect = False
                self.segment_triggered = False

        if self.speech_start > 0.0:
            self.buffer.append(arr)
            self.buf_samples += arr.size
            self.buf_seconds = self.buf_samples / SAMPLE_RATE
            if now - self._last_progress >= 1.0:
                self._last_progress = now
                print(f"[{_ts()}]   ... 已累积 {self.buf_seconds:.1f}s")

            # 满 7 秒立即判定（只判一次，不匹配；段结束才用完整音频匹配）
            if not self.checked_at_collect and self.buf_seconds >= HUM_COLLECT_SEC:
                self.checked_at_collect = True
                self._judge_at_collect()

    def _judge_at_collect(self):
        audio = np.concatenate(list(self.buffer))
        ok, m = judge(audio)
        print(f"[{_ts()}] ⚡ 满 7 秒判定（时长 {self.buf_seconds:.2f}s，fl{JUDGE_FRAME_LENGTH}）")
        self._print_metrics(m)
        if ok:
            self.segment_triggered = True
            print("        判定：✅ 哼唱 → 继续收集，段结束用完整音频匹配")
        else:
            print("        判定：❌ 非哼唱 → 段结束兜底再判")

    def _finish(self):
        if self.buf_seconds < HUM_COLLECT_SEC:
            print(f"[{_ts()}] ⏹ 段结束，时长 {self.buf_seconds:.2f}s < {HUM_COLLECT_SEC}s，丢弃（未分析）")
            return

        audio = np.concatenate(list(self.buffer))
        print(f"[{_ts()}] ⏹ 段结束（时长 {self.buf_seconds:.2f}s）")

        if self.segment_triggered:
            print("        满 7 秒已判定为哼唱，用完整音频匹配（后续语音已加入）")
            self._match_full(audio)
            return

        # 满 7 秒未通过 → 段结束用完整音频兜底判定
        print("        满 7 秒未通过，段结束用完整音频兜底判定")
        ok, m = judge(audio)
        self._print_metrics(m)
        if not ok:
            print("        判定：❌ 非哼唱")
            return
        self.segment_triggered = True
        self._match_full(audio)

    def _match_full(self, audio):
        midi = extract_match_midi(audio)
        title, score, offset = match_song(self.refs, midi)
        if title:
            print(f"        匹配：✅ 《{title}》 分数={score:.3f} 偏移={offset:.1f}s")
        else:
            print(f"        匹配：❌ 未达阈值（最高分 {score:.3f} < {MATCH_THRESHOLD}）")

    def _print_metrics(self, m):
        def mark(cond):
            return "✅" if cond else "❌"
        print(f"        voiced_ratio = {m['ratio']:.3f}  (阈值 {F0_VOICED_RATIO}) {mark(m['ratio'] >= F0_VOICED_RATIO)}")
        print(f"        stable_ratio = {m['stable_ratio']:.3f}  (阈值 {F0_STABLE_RATIO}) {mark(m['stable_ratio'] >= F0_STABLE_RATIO)}")
        print(f"        unique_notes = {m['unique_notes']}  (阈值 {F0_UNIQUE_NOTES}) {mark(m['unique_notes'] >= F0_UNIQUE_NOTES)}")
        print(f"        voiced_frames = {m['voiced_frames']} / {m['total_frames']}")


def main():
    print("=" * 60)
    print("独立哼唱检测 + 歌曲匹配模拟（与项目算法一致）")
    print("=" * 60)
    print(f"采样率            : {SAMPLE_RATE} Hz / 帧 {CHUNK_MS}ms")
    print(f"VAD 能量阈值      : {ENERGY_THRESHOLD}")
    print(f"段结束静音阈值    : {SILENCE_THRESHOLD}s")
    print(f"哼唱最少时长      : {HUM_COLLECT_SEC}s（满此值立即判定）")
    print(f"判定 yin          : fl={JUDGE_FRAME_LENGTH}, hop={HOP}")
    print(f"匹配 yin          : fl={MATCH_FRAME_LENGTH}, hop={HOP}")
    print(f"voiced_ratio 阈值 : {F0_VOICED_RATIO}")
    print(f"stable_ratio 阈值 : {F0_STABLE_RATIO} (half_step={F0_STABLE_HALF_STEP})")
    print(f"unique_notes 阈值 : {F0_UNIQUE_NOTES}")
    print(f"匹配余弦阈值      : {MATCH_THRESHOLD}")
    print("=" * 60)

    refs = load_refs()
    print(f"曲库已加载 {len(refs)} 首: {list(refs.keys())}")
    if not refs:
        print("警告：曲库为空，匹配将无法命中。请先运行 regen_pitch.py 生成 npy。")

    try:
        import pyaudio
    except ImportError:
        print("缺少 pyaudio，请先安装：pip install pyaudio")
        return

    pa = pyaudio.PyAudio()
    try:
        info = pa.get_default_input_device_info()
        print(f"默认麦克风: {info['name']} (设备采样率 {int(info['defaultSampleRate'])}Hz)")
    except Exception:
        print("未获取到默认麦克风信息")

    try:
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
    except Exception as e:
        print(f"打开麦克风失败: {e}")
        pa.terminate()
        return

    print(f"\n开始监听（首次分析会加载 librosa，可能卡几秒）。Ctrl+C 退出。\n")

    det = HumDetector(refs)
    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            det.feed(arr)
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


if __name__ == "__main__":
    main()
