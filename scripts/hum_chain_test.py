# -*- coding: utf-8 -*-
# scripts/hum_chain_test.py
r"""接龙链路实测：把曲库的人声片段当作"用户哼唱"，喂进真实检测器 → 匹配 → 接唱定位

覆盖：TBHumDetect（VAD + 满 7 秒判定 + 段结束）→ TBHumMatch（余弦 / DTW）→ TBNextLine（接唱定位）

用法：
    runtime\311\python.exe scripts\hum_chain_test.py
    runtime\311\python.exe scripts\hum_chain_test.py --only "云女孩" --only Avid
    runtime\311\python.exe scripts\hum_chain_test.py --seconds 12 --limit 6
"""

import argparse
import os
import re
import sys
import tempfile
import time
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(tempfile.gettempdir(), "mew_numba"))

SR = 16000
CHUNK_MS = 200
CHUNK = int(SR * CHUNK_MS / 1000)
MEOW_DIR = os.path.join("character", "songs", "meow_list")
TIME_RE = re.compile(r"\[(\d{2}):(\d{2})\.(\d{3})\](.*)")


def read_wav_mono(path):
    """解码为 16k 单声道 int16 PCM（与 SenseVoice 喂给检测器的格式一致）"""
    import librosa
    y, _ = librosa.load(path, sr=SR, mono=True)
    return np.clip(y * 32767.0, -32768, 32767).astype(np.int16)


def lrc_times(title):
    path = os.path.join(MEOW_DIR, title, f"{title}.lrc")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f.read().splitlines():
            m = TIME_RE.match(line.strip())
            if m:
                out.append(int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 1000.0)
    return sorted(out)


def pick_start(times, total_sec, dur):
    """从中间段挑一个落在歌词句首附近的起点，保证接唱有下一句"""
    if not times:
        return max(0.0, total_sec * 0.45)
    target = total_sec * 0.45
    cand = [t for t in times if t <= target + 20 and t + dur < total_sec - 5]
    return cand[-1] if cand else times[0]


def write_wav(path, frames):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(frames.astype(np.int16).tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=[], help="指定歌名（可多次）")
    ap.add_argument("--seconds", type=float, default=12.0, help="喂入时长（秒）")
    ap.add_argument("--limit", type=int, default=0, help="最多测几首")
    args = ap.parse_args()

    from func.toolbox.meowsongs.hum_detect.hum_detect import TBHumDetect
    from func.toolbox.meowsongs.pass_the_baton.hum_match import TBHumMatch
    from func.toolbox.meowsongs.pass_the_baton.next_line import TBNextLine
    from func.toolbox.meowsongs.config import TBMeowSongsConfig
    from func.sensevoice.config import SenseVoiceConfig

    cfg = TBMeowSongsConfig()
    silence_need = float(SenseVoiceConfig().silence_threshold) + 0.3
    detect = TBHumDetect()
    matcher = TBHumMatch()
    nextline = TBNextLine()

    titles = args.only or [d for d in sorted(os.listdir(MEOW_DIR))
                           if os.path.isdir(os.path.join(MEOW_DIR, d))
                           and os.path.exists(os.path.join(MEOW_DIR, d, f"{d}_vocal.wav"))]
    if args.limit:
        titles = titles[:args.limit]

    print(f"素材 {len(titles)} 首 | 喂入 {args.seconds:.0f}s | "
          f"判定阈值 voiced≥{cfg.f0_voiced_ratio} stable≥{cfg.f0_stable_ratio} "
          f"notes≥{cfg.f0_unique_notes} | 匹配阈值 {cfg.match_threshold} 分差 {cfg.min_margin}")
    print(f"{'歌曲':<16}{'判定':<8}{'指标 r/s/n':<20}{'识别':<14}{'分数':>6}{'分差':>6}"
          f"{'偏移误差':>9}{'接唱':>5}")
    print("-" * 104)

    tmpdir = tempfile.mkdtemp(prefix="mew_hum_")
    hit_song = hit_line = total = 0
    for title in titles:
        wav = os.path.join(MEOW_DIR, title, f"{title}_vocal.wav")
        pcm = read_wav_mono(wav)
        total_sec = pcm.size / SR
        times = lrc_times(title)
        start = pick_start(times, total_sec, args.seconds)
        seg = pcm[int(start * SR):int((start + args.seconds) * SR)]
        if seg.size < (args.seconds - 1) * SR:
            print(f"{title:<16}跳过硬（素材不足）")
            continue

        # 清空上一首残留状态：段结束靠静音，先补一段静音
        detect.feed(np.zeros(int(SR * 0.4), dtype=np.int16).tobytes())
        time.sleep(silence_need)

        seq0 = detect.get_hum_event_seq()
        for i in range(0, seg.size, CHUNK):
            detect.feed(seg[i:i + CHUNK].tobytes())
        time.sleep(silence_need)
        detect.feed(np.zeros(CHUNK, dtype=np.int16).tobytes())
        passed = detect.get_hum_event_seq() > seq0
        m = detect.get_last_metrics()
        metric_txt = "%s/%s/%s" % (m.get("ratio", 0.0), m.get("stable_ratio", 0.0),
                                   m.get("unique_notes", 0))
        hum_dur = detect.get_last_hum_duration() or (seg.size / SR)
        detect.consume_hum_audio()

        # 匹配链路用本次喂入的同一段音频，与判定结论解耦，便于分开看两段表现
        path = os.path.join(tmpdir, "hum.wav")
        write_wav(path, seg)
        got_title, off, score, second, margin = matcher.match(path)
        ok_song = got_title == title
        total += 1
        hit_song += int(ok_song)

        ok_match = bool(got_title and score >= cfg.match_threshold and margin >= cfg.min_margin)
        use_title, use_off = (got_title, off) if ok_match else (None, 0.0)
        user_lyric, start_sec, end_sec, lines = nextline.locate(use_title or "", use_off, hum_dur)
        expect = [t for t in times if t > start + hum_dur]
        expect_line = expect[0] if expect else None
        ok_line = bool(start_sec is not None and expect_line is not None
                       and abs(start_sec - expect_line) <= 3.0)
        hit_line += int(ok_line)

        print(f"{title:<16}{('通过' if passed else '拒绝'):<8}{metric_txt:<20}"
              f"{str(got_title):<14}{score:>6.3f}{margin:>6.3f}"
              f"{off - start:>+8.1f}s{('OK' if ok_line else 'X'):>5}")
        if ok_song and not ok_line:
            print(f"{'':<16}接唱起点 {start_sec:.1f}s / 期望 {expect_line:.1f}s")

    print("-" * 104)
    print(f"歌曲命中 {hit_song}/{total}   接唱定位命中 {hit_line}/{total}")


if __name__ == "__main__":
    main()
