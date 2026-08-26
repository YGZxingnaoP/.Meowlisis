# -*- coding: utf-8 -*-
"""
hum_detect_sim.py —— 独立哼唱检测模拟脚本（不依赖项目任何模块）

用途：
    保持麦克风开启，实时采集 16k 单声道音频，按项目 hum_detect 的相同逻辑
    做 VAD 分段 + pyin 音高/旋律判定，并实时打印每段语音的各项指标，
    用于对照微调哼唱检测阈值。

用法：
    runtime\\python.exe hum_detect_sim.py
    或  python hum_detect_sim.py

依赖（仅第三方库，与项目解耦）：
    numpy / librosa / pyaudio

退出：
    Ctrl+C
"""

import sys
import time
from collections import deque

import numpy as np

# ==================== 可调参数（微调这里） ====================
SAMPLE_RATE = 16000            # 采样率，固定 16k（与项目一致）
CHUNK_MS = 200                 # 每帧时长 ms（与 SenseVoice chunk_size_ms 一致）
CHUNK = int(SAMPLE_RATE * CHUNK_MS / 1000)

ENERGY_THRESHOLD = 400         # VAD 能量阈值（RMS，int16 幅度）。越大越不敏感
SILENCE_THRESHOLD = 2.0        # 段结束静音阈值（秒）。连续静音超过此值即分段

HUM_COLLECT_SEC = 7.0          # 哼唱最少累积时长（秒）。不足则丢弃不分析

F0_MIN = 80                    # pyin 最低基频（Hz）
F0_MAX = 800                   # pyin 最高基频（Hz）
FRAME_LENGTH = 1024            # pyin 帧长

F0_VOICED_RATIO = 0.6          # 有声音高帧占比阈值（越高要求哼唱越连续）
F0_STABLE_RATIO = 0.6          # 稳定帧占比阈值（越高要求音高越稳）
F0_STABLE_HALF_STEP = 0.5      # 相邻帧音高差 < 此半音数视为稳定帧（越小越严）
F0_UNIQUE_NOTES = 3            # 唯一音符数阈值（越高要求旋律变化越多）

VERBOSE_FRAME = False          # True 时打印每帧能量（很刷屏，调试用）
# ============================================================


def _ts():
    return time.strftime("%H:%M:%S")


def analyze(audio: np.ndarray):
    """对一段音频做 pyin 音高 + 旋律稳定性分析，返回 (是否判定为哼唱, 指标 dict)"""
    import librosa

    f0, voiced, _ = librosa.pyin(
        audio.astype(np.float32) / 32768.0,
        fmin=F0_MIN, fmax=F0_MAX,
        sr=SAMPLE_RATE, frame_length=FRAME_LENGTH,
    )
    valid = f0[voiced]
    if valid.size < 3:
        return False, {
            "voiced_frames": int(valid.size),
            "total_frames": int(f0.size),
            "ratio": 0.0,
            "stable_ratio": 0.0,
            "unique_notes": 0,
        }

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
    return ok, {
        "voiced_frames": int(valid.size),
        "total_frames": int(f0.size),
        "ratio": ratio,
        "stable_ratio": stable_ratio,
        "unique_notes": unique_notes,
    }


class HumDetector:
    """复刻项目 hum_detect 的 VAD 分段逻辑：语音段进行中才累积，段结束清空"""

    def __init__(self):
        self.buffer = deque()
        self.buf_samples = 0
        self.buf_seconds = 0.0
        self.speech_start = 0.0
        self.last_sound = 0.0
        self._last_progress = 0.0

    def feed(self, arr: np.ndarray):
        rms = float(np.sqrt(np.mean(arr ** 2)))
        now = time.time()

        if rms >= ENERGY_THRESHOLD:
            # 有效语音
            if self.speech_start == 0.0:
                self.speech_start = now
                self._last_progress = now
                print(f"[{_ts()}] 🔊 语音段开始")
            self.last_sound = now
        else:
            # 静音超阈值 → 段结束，分析并清空重来
            if self.speech_start > 0.0 and now - self.last_sound >= SILENCE_THRESHOLD:
                self._finish()
                self.speech_start = 0.0
                self.last_sound = 0.0
                self.buffer.clear()
                self.buf_samples = 0
                self.buf_seconds = 0.0

        # 语音段进行中才累积：只保留当前段的音频
        if self.speech_start > 0.0:
            self.buffer.append(arr)
            self.buf_samples += arr.size
            self.buf_seconds = self.buf_samples / SAMPLE_RATE
            if now - self._last_progress >= 1.0:
                self._last_progress = now
                print(f"[{_ts()}]   ... 已累积 {self.buf_seconds:.1f}s")

    def _finish(self):
        dur = self.buf_seconds
        if dur < HUM_COLLECT_SEC:
            print(f"[{_ts()}] ⏹ 段结束，时长 {dur:.2f}s < {HUM_COLLECT_SEC}s，丢弃（未分析）")
            return

        print(f"[{_ts()}] ⏹ 段结束，时长 {dur:.2f}s，开始分析...")
        ok, m = analyze(np.concatenate(list(self.buffer)))

        def mark(cond):
            return "✅" if cond else "❌"

        print(f"        voiced_ratio = {m['ratio']:.3f}  (阈值 {F0_VOICED_RATIO}) {mark(m['ratio'] >= F0_VOICED_RATIO)}")
        print(f"        stable_ratio = {m['stable_ratio']:.3f}  (阈值 {F0_STABLE_RATIO}) {mark(m['stable_ratio'] >= F0_STABLE_RATIO)}")
        print(f"        unique_notes = {m['unique_notes']}  (阈值 {F0_UNIQUE_NOTES}) {mark(m['unique_notes'] >= F0_UNIQUE_NOTES)}")
        print(f"        voiced_frames = {m['voiced_frames']} / {m['total_frames']}")

        if ok:
            print(f"        判定：✅ 哼唱")
        else:
            print(f"        判定：❌ 非哼唱")


def main():
    # 打印当前参数
    print("=" * 60)
    print("独立哼唱检测模拟（不依赖项目）")
    print("=" * 60)
    print(f"采样率            : {SAMPLE_RATE} Hz / 帧 {CHUNK_MS}ms")
    print(f"VAD 能量阈值      : {ENERGY_THRESHOLD}")
    print(f"段结束静音阈值    : {SILENCE_THRESHOLD}s")
    print(f"哼唱最少时长      : {HUM_COLLECT_SEC}s")
    print(f"pyin 频率范围     : {F0_MIN}~{F0_MAX} Hz, frame={FRAME_LENGTH}")
    print(f"voiced_ratio 阈值 : {F0_VOICED_RATIO}")
    print(f"stable_ratio 阈值 : {F0_STABLE_RATIO} (half_step={F0_STABLE_HALF_STEP})")
    print(f"unique_notes 阈值 : {F0_UNIQUE_NOTES}")
    print("=" * 60)

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

    det = HumDetector()
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
