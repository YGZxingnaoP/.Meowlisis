# -*- coding: utf-8 -*-
# scripts/tts/tts_tail_test.py
# 流式 TTS「播放末尾能听到最后一个音又说了一遍 / 突然的不自然声音」的复现与判定脚本。
#
# 完全按 config.yml 的现值发请求（和 func/tts/gpt_sovits.py 的 payload 同一套参数），
# 把 PCM 存成 wav 让你亲耳听，同时给出客观指标：
#   * 末段尖锐程度：末段最大相邻采样跳变 ÷ 它周围 4ms 的常态跳变。
#     末块没做交叉淡化时会硬拼一下，这个倍数会突然飙高（正常语音一般 < 5）。
#   * 尾部自相似：末尾 80ms 与紧邻前 80ms 的归一化相关（重叠区 = overlap_length × 1280）。
#     接近 1 说明最后一小段和前面几乎一样；长元音/纯音本身也会偏高，仅作参考。
#
# 用法（在仓库根目录跑，用内置运行时）：
#   runtime\311\python.exe scripts\tts\tts_tail_test.py                 # 默认：happy 参数，合成一句并播放
#   runtime\311\python.exe scripts\tts\tts_tail_test.py --emotion neutral   # 换成中性（基础参数）
#   runtime\311\python.exe scripts\tts\tts_tail_test.py --replay        # 秒播上次结果，不重新合成
#   runtime\311\python.exe scripts\tts\tts_tail_test.py --play-raw      # 改用生产播放器的管道方式放
#   runtime\311\python.exe scripts\tts\tts_tail_test.py --no-play       # 只存 wav 不放
#   runtime\311\python.exe scripts\tts\tts_tail_test.py --emotion happy --repeat 3
#   runtime\311\python.exe scripts\tts\tts_tail_test.py --text "自定义一句话"
#   runtime\311\python.exe scripts\tts\tts_tail_test.py --dry-run       # 只打印将要发的请求
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import wave

import numpy as np
import requests
import yaml

try:                                    # Windows 控制台偶发 GBK，中文输出别炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(ROOT, "config.yml")
REF_CONFIG_PATH = os.path.join(ROOT, "character", "ref_audio", "config.json")
MPV_PATH = os.path.join(ROOT, "mpv.exe")

# 默认只跑一句短的：合成一句大约 5~10 秒，别让人干等。
# 想听短/中/长三种，加 --all。
DEFAULT_TEXTS = ["没看到你开B站啊。"]
ALL_TEXTS = [
    "没看到你开B站啊。",
    "屏幕归屏幕，看归看，没看到你开B站啊。",
    "这个有月动画种草激励，还挂现金钩子，别被勾着就点，真的种草才值那几秒。",
]


# ==================== 配置 ====================
def load_tts_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    gpt = ((cfg.get("tts") or {}).get("gpt-sovits")) or {}
    return cfg.get("tts") or {}, gpt


def load_ref_audio(character, emotion):
    with open(REF_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f) or {}
    if character:
        if character not in data:
            raise SystemExit("character/ref_audio/config.json 里没有角色「%s」，可选：%s"
                             % (character, "、".join(data.keys())))
        name = character
    elif len(data) == 1:
        name = next(iter(data))
    else:
        raise SystemExit("有多个角色，请用 --character 指定：%s" % "、".join(data.keys()))
    refs = data[name] or {}
    if emotion and emotion in refs:
        ref = refs[emotion]
    elif "neutral" in refs:
        ref = refs["neutral"]
    elif refs:
        ref = next(iter(refs.values()))
    else:
        raise SystemExit("角色「%s」没有配置参考音频" % name)
    path = ref.get("audio") or ""
    if path and not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    return name, {"audio": path, "text": ref.get("text") or "", "lang": ref.get("lang") or "zh"}


# ==================== 采样参数（与 func/tts/emotion.build_sampling_params 一致）====================
def build_sampling_params(gpt, emotion, intensity=3.0):
    base = {
        "top_k": int(gpt.get("top_k", 15)),
        "top_p": float(gpt.get("top_p", 1.0)),
        "temperature": float(gpt.get("temperature", 1.0)),
        "repetition_penalty": float(gpt.get("repetition_penalty", 1.35)),
        "noise_scale": float(gpt.get("noise_scale", 0.5)),
        "speed": float(gpt.get("speed", 1.0)),
    }
    emo = dict(((gpt.get("emotion_params") or {}).get(emotion) or {}))
    if not emo:
        return base
    intensity = max(0.0, min(5.0, float(intensity)))
    factor = intensity / 3.0 if intensity < 3.0 else 1.0 + (intensity - 3.0) * 0.25
    for key, value in emo.items():
        if isinstance(value, (int, float)) and key in base:
            new = base[key] + (value - base[key]) * factor
            base[key] = round(new) if isinstance(base[key], int) else new
    return base


def build_payload(text, gpt, ref, emotion, intensity, streaming_mode, text_lang):
    params = build_sampling_params(gpt, emotion, intensity)
    return {
        "text": text,
        "text_lang": text_lang or gpt.get("text_lang", "zh"),
        "ref_audio_path": os.path.abspath(ref["audio"]),
        "prompt_text": ref["text"],
        "prompt_lang": ref.get("lang") or "zh",
        "media_type": gpt.get("media_type", "raw"),
        "streaming_mode": streaming_mode,
        "fragment_interval": float(gpt.get("fragment_interval", 0.0)),
        "min_chunk_length": int(gpt.get("min_chunk_length", 12)),
        "overlap_length": int(gpt.get("overlap_length", 2)),
        "top_k": params["top_k"],
        "top_p": params["top_p"],
        "temperature": params["temperature"],
        "repetition_penalty": params["repetition_penalty"],
        "noise_scale": params["noise_scale"],
        "speed_factor": params["speed"],
    }


# ==================== 合成 ====================
def synth(endpoint, payload, on_chunk=None):
    """按生产同款方式 POST+流式收字节

    on_chunk：每收到一块就回调（--live 时直接灌给 mpv，边收边放）
    返回 (pcm, chunk_sizes, first_byte_sec, total_sec)
    """
    t0 = time.time()
    first = None
    chunks = []
    try:
        resp = requests.post(endpoint, json=payload, stream=True, timeout=(5, 300))
    except Exception as exc:
        raise SystemExit("连不上 GPT-SoVITS（%s）：%s\n先确认服务已启动、地址和 config.yml 一致。"
                         % (endpoint, exc))
    if resp.status_code != 200:
        raise SystemExit("GPT-SoVITS 返回 %s：%s" % (resp.status_code, resp.text[:400]))
    sizes = []
    try:
        for chunk in resp.iter_content(chunk_size=4096):
            if not chunk:
                continue
            if first is None:
                first = time.time() - t0
            chunks.append(chunk)
            sizes.append(len(chunk))
            if on_chunk is not None:
                on_chunk(chunk)
    finally:
        resp.close()
    pcm = b"".join(chunks)
    media_type = str(payload.get("media_type") or "raw").lower()
    if media_type == "wav" and pcm[:4] == b"RIFF":
        pcm = pcm[44:]
    return pcm, sizes, (first or 0.0), time.time() - t0


def process_pcm(pcm, sr, fade_in_ms=5.0, fade_out_ms=40.0, tail_ms=250.0):
    """按生产播放的做法处理一遍：段首淡入 + 段尾淡出 + 尾静音

    直接 `mpv 文件.wav` 是"文件结束就关声卡"，听感就是一刀切断；
    生产播放器是"淡出 + 补静音后再收工"，这里复刻同一条路径，方便你听真实效果。
    """
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n_in = min(x.size, int(sr * fade_in_ms / 1000.0))
    n_out = min(x.size, int(sr * fade_out_ms / 1000.0))
    if n_in > 0:
        x[:n_in] *= np.linspace(0.0, 1.0, n_in, dtype=np.float32)
    if n_out > 0:
        x[-n_out:] *= np.linspace(1.0, 0.0, n_out, dtype=np.float32)
    x = np.clip(x, -32768, 32767).astype(np.int16)
    tail = np.zeros(max(0, int(sr * tail_ms / 1000.0)), dtype=np.int16)
    return np.concatenate([x, tail]).tobytes()


class LiveSink:
    """把收到的 PCM 立刻灌进 mpv：不用等整段合成完就能听见（--live）"""

    def __init__(self, sr):
        self.sr = sr
        self.proc = None
        if not os.path.exists(MPV_PATH):
            return
        cmd = [
            MPV_PATH, "--no-config", "--no-video", "--no-terminal", "--idle=no",
            "--force-window=no", "--demuxer=rawaudio", "--demuxer-rawaudio-format=s16le",
            "--demuxer-rawaudio-channels=1", "--demuxer-rawaudio-rate=%d" % sr,
            "--audio-buffer=0.3", "--demuxer-readahead-secs=0.5", "--cache=no", "-",
        ]
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            print("           边收边放启动失败：%s" % exc)
            self.proc = None

    def feed(self, data):
        if self.proc is None:
            return
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except Exception:
            self.proc = None

    def close(self, tail_ms=60):
        if self.proc is None:
            return
        try:
            self.proc.stdin.write(b"\x00" * int(self.sr * 2 * tail_ms / 1000.0))
            self.proc.stdin.flush()
        except Exception:
            pass
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=180)
        except Exception:
            pass
        self.proc = None


# ==================== 缓存（同样的文本+参数，第二次直接播，不重新合成）====================
def cache_path(out_dir, text, streaming, emotion, intensity, gpt, ref=None):
    ref = ref or {}
    try:
        ref_stamp = (ref.get("audio") or "", os.path.getmtime(ref.get("audio") or ""))
    except Exception:
        ref_stamp = (ref.get("audio") or "", 0.0)
    key = json.dumps({
        "text": text, "streaming": bool(streaming), "emotion": emotion,
        "intensity": intensity, "media_type": gpt.get("media_type"),
        "streaming_mode": gpt.get("streaming_mode"),
        "min_chunk_length": gpt.get("min_chunk_length"),
        "overlap_length": gpt.get("overlap_length"),
        "top_k": gpt.get("top_k"), "top_p": gpt.get("top_p"),
        "temperature": gpt.get("temperature"),
        "repetition_penalty": gpt.get("repetition_penalty"),
        "noise_scale": gpt.get("noise_scale"), "speed": gpt.get("speed"),
        # 参考音频也进 key：换了参考音频（比如 happy.wav 被替换）就不该命中旧缓存
        "ref_audio": ref_stamp[0], "ref_mtime": ref_stamp[1],
    }, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return os.path.join(out_dir, "tts_%s_%s.wav" % ("stream" if streaming else "plain", digest))


def read_wav_frames(path):
    with wave.open(path, "rb") as w:
        return w.readframes(w.getnframes())


def latest_wav(out_dir):
    try:
        names = [os.path.join(out_dir, n) for n in os.listdir(out_dir) if n.lower().endswith(".wav")]
    except Exception:
        return ""
    return max(names, key=os.path.getmtime) if names else ""


# ==================== 诊断 ====================
def _ncorr(a, b):
    a = a - a.mean()
    b = b - b.mean()
    den = float(np.linalg.norm(a) * np.linalg.norm(b)) or 1e-9
    return float(np.dot(a, b) / den)


def best_ncorr(tail, prev, search=320):
    """在 prev 里滑动 ±search 采样找与 tail 最像的一段（sola 的搜索窗口同量级）"""
    if tail.size == 0 or prev.size < tail.size:
        return -1.0
    top = min(search, prev.size - tail.size)
    best = -1.0
    for shift in range(0, top + 1):
        best = max(best, _ncorr(prev[shift:shift + tail.size], tail))
    return best


def analyze(pcm, gpt, sr, tail_ms=400):
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    report = {"samples": int(x.size), "sec": x.size / float(sr) if sr else 0.0}
    if x.size < sr // 2:
        report["error"] = "音频太短，无法判断"
        return report, x
    diff = np.abs(np.diff(x))
    tail_n = min(x.size // 3, max(1, int(sr * tail_ms / 1000.0)))
    tail = diff[-tail_n:]
    idx = int(np.argmax(tail))
    gidx = diff.size - tail_n + idx
    # 单点跳变要跟"它周围"比：真正的硬切是孤立尖峰，而不是整体变响
    win = max(2, int(sr * 0.002))
    lo, hi = max(0, gidx - win), min(diff.size, gidx + win + 1)
    local = float(np.median(diff[lo:hi])) or 1.0
    report["tail_jump"] = float(tail[idx])
    report["tail_local"] = local
    report["tail_spike"] = float(tail[idx] / local)
    report["tail_jump_from_end_ms"] = float((tail_n - idx) / sr * 1000.0)
    report["p999"] = float(np.percentile(diff, 99.9)) or 1.0
    report["tail_jump_ratio"] = float(tail[idx] / report["p999"])
    report["peak"] = float(np.abs(x).max())
    report["rms"] = float(np.sqrt(np.mean(np.square(x))))

    # 重叠区长度候选：语义帧 25Hz/50Hz 两种模型都算一遍
    overlap_length = int(gpt.get("overlap_length", 2))
    cands = sorted({overlap_length * int(sr / 25), overlap_length * int(sr / 50)} - {0})
    report["overlap_candidates"] = cands
    sims = {}
    for length in cands:
        if x.size >= 3 * length:
            sims[length] = best_ncorr(x[-length:], x[-2 * length:-length])
    report["tail_similarity"] = sims
    return report, x


def write_wav(path, pcm, sr):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)


def play(path):
    """先试 mpv（和生产同一个播放器），失败再退回系统 winsound，最后至少告诉你文件在哪"""
    import subprocess
    if os.path.exists(MPV_PATH):
        try:
            proc = subprocess.run([MPV_PATH, "--no-config", "--no-video",
                                   "--msg-level=all=warn", str(path)],
                                  capture_output=True, text=True, timeout=180)
            if proc.returncode == 0:
                print("           播放：mpv")
                return True
            lines = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()][-3:]
            print("           播放：mpv 失败（exit %s）%s" % (proc.returncode, " / ".join(lines)))
        except Exception as exc:
            print("           播放：mpv 异常 %s" % exc)
    else:
        print("           播放：没找到 mpv.exe（%s）" % MPV_PATH)
    if sys.platform == "win32":
        try:
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME)
            print("           播放：系统播放器（winsound）")
            return True
        except Exception as exc:
            print("           播放：winsound 失败 %s" % exc)
    print("           没能播放，wav 在这里（手工打开也行）：%s" % path)
    return False


def play_raw(pcm, sr, tail_silence_ms=60, hold_ms=1200):
    """按生产播放器的方式喂 mpv：裸 PCM 走 stdin，末尾补静音后关 stdin

    为什么关管道前还要 hold_ms：关掉 mpv 就等于关声卡，某些机器会"嗒"一声；
    如果最后一个字节刚写完就关，这一声就贴在你的最后一个字后面。
    先多喂一段静音、让它落在静音里，再关。
    """
    import subprocess
    if not os.path.exists(MPV_PATH):
        print("           播放：没找到 mpv.exe，跳过管道方式")
        return False
    silence = b"\x00" * int(sr * 2 * (tail_silence_ms + hold_ms) / 1000.0)
    cmd = [
        MPV_PATH, "--no-config", "--no-video", "--no-terminal", "--idle=no",
        "--force-window=no", "--demuxer=rawaudio", "--demuxer-rawaudio-format=s16le",
        "--demuxer-rawaudio-channels=1", "--demuxer-rawaudio-rate=%d" % sr,
        "--audio-buffer=0.3", "--demuxer-readahead-secs=0.5", "--cache=no", "-",
    ]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            proc.stdin.write(pcm + silence)
            proc.stdin.flush()
        finally:
            proc.stdin.close()
        code = proc.wait(timeout=180)
        print("           播放：mpv 管道方式（exit %s，尾部静音 %.0fms + 收尾 %.0fms）"
              % (code, tail_silence_ms, hold_ms))
        return code == 0
    except Exception as exc:
        print("           播放：mpv 管道方式失败 %s" % exc)
        return False


def print_report(tag, report, wav_path, sizes, first_sec, total_sec, sr):
    print("  %-8s %s" % (tag, os.path.basename(wav_path)))
    print("           时长 %.2fs  (%d 采样)" % (report.get("sec", 0.0), report.get("samples", 0)))
    print("           首包 %.2fs  总耗时 %.2fs  收到 %d 块  末块 %d 字节"
          % (first_sec, total_sec, len(sizes), sizes[-1] if sizes else 0))
    if "error" in report:
        print("           判定：%s" % report["error"])
        return
    print("           末段最大跳变 %.0f（周围常态 %.0f，尖峰 %.1f 倍）距结尾 %.0fms"
          % (report["tail_jump"], report["tail_local"], report["tail_spike"],
             report["tail_jump_from_end_ms"]))
    print("           电平 peak %.0f / RMS %.0f%s"
          % (report["peak"], report.get("rms", 0.0),
             "  ← 全是静音，先查服务端" if report["peak"] < 16 else ""))
    for length, sim in (report.get("tail_similarity") or {}).items():
        print("           尾部自相似(%dms 窗口) = %.2f" % (length * 1000 // sr, sim))
    flag = []
    if report["peak"] < 16:
        print("           判定：整段是静音（peak=0），先去看 logs/svc_sovits_*.log")
        return
    if report["tail_spike"] >= 8.0:
        flag.append("末段有孤立尖峰 %.0f 倍（硬切/爆音）" % report["tail_spike"])
    print("           判定：%s" % ("；".join(flag) if flag else "末段无明显拼接痕迹"))


# ==================== 主流程 ====================
def main():
    ap = argparse.ArgumentParser(description="流式 TTS 末尾重复/爆音复现脚本（按 config.yml 现值）")
    ap.add_argument("--character", default="", help="角色名（ref_audio/config.json 的 key，缺省自动取唯一一个）")
    ap.add_argument("--emotion", default="happy",
                    help="用哪个情绪的参考音频/采样参数（默认 happy）")
    ap.add_argument("--intensity", type=float, default=3.0, help="情绪强度 0~5，默认 3")
    ap.add_argument("--mode", choices=["config", "stream", "nostream"], default="config",
                    help="config=用 config.yml 的 streaming_mode（默认）；stream/nostream 强制开关流式")
    ap.add_argument("--ab", action="store_true", help="同一句分别用流式和非流式各跑一次做对照")
    ap.add_argument("--text", default="", help="自定义测试文本（只跑这一句）")
    ap.add_argument("--all", action="store_true", help="跑短/中/长三句（默认只跑一句短的）")
    ap.add_argument("--repeat", type=int, default=1, help="每句重复几次（听感有随机性，多跑几次）")
    ap.add_argument("--force", action="store_true", help="忽略缓存，强制重新合成")
    ap.add_argument("--live", action="store_true",
                    help="边收边放：第一块音频到了就开始响，不整段等（会有合成跟不上播放的断续）")
    ap.add_argument("--replay", action="store_true",
                    help="不合成，直接重放上一次生成的 wav（秒播）")
    ap.add_argument("--text-lang", default="", help="覆盖 text_lang（默认取 config.yml）")
    ap.add_argument("--out", default="", help="wav 输出目录（默认系统临时目录）")
    ap.add_argument("--play", dest="play", action="store_true", default=True,
                    help="合成完自动播放（默认开）")
    ap.add_argument("--no-play", dest="play", action="store_false",
                    help="只存 wav，不自动播放")
    ap.add_argument("--play-file", action="store_true",
                    help="直接用 mpv 播原始 wav（不做淡出/补静音）——用来对比「原始 vs 生产处理」")
    ap.add_argument("--fade-ms", type=float, default=40.0, help="播放时段尾淡出毫秒数（默认 40）")
    ap.add_argument("--tail-ms", type=float, default=250.0, help="播放时尾部补静音毫秒数（默认 250）")
    ap.add_argument("--play-raw", action="store_true",
                    help="改用生产播放器的方式喂 mpv（裸 PCM 走 stdin + 末尾补 60ms 静音后关管道），可一起用")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要发送的请求，不真的合成")
    args = ap.parse_args()

    _, gpt = load_tts_config()
    character, ref = load_ref_audio(args.character, args.emotion)
    endpoint = str(gpt.get("gpt_sovits_url", "http://127.0.0.1:9880")).rstrip("/") + "/tts"
    sr = int(gpt.get("sample_rate", 32000))
    cfg_streaming = gpt.get("streaming_mode", 2)
    out_dir = args.out or os.path.join(tempfile.gettempdir(), "tts_tail_test")
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 72)
    print("GPT-SoVITS   %s" % endpoint)
    print("角色/参考音频 %s / %s (%s)" % (character, os.path.basename(ref["audio"]), args.emotion))
    print("配置          streaming_mode=%s media_type=%s overlap_length=%s min_chunk_length=%s "
          "fragment_interval=%s sample_rate=%s"
          % (cfg_streaming, gpt.get("media_type"), gpt.get("overlap_length"),
             gpt.get("min_chunk_length"), gpt.get("fragment_interval"), sr))
    params = build_sampling_params(gpt, args.emotion, args.intensity)
    print("情绪参数      emotion=%s intensity=%.1f → temperature=%.2f speed=%.2f top_k=%d "
          "noise=%.2f rep=%.2f"
          % (args.emotion, args.intensity, params["temperature"], params["speed"],
             params["top_k"], params["noise_scale"], params["repetition_penalty"]))
    emo_map = (gpt.get("emotion_params") or {})
    if args.emotion not in emo_map:
        print("              注意：%s 没有 emotion_params，上面的参数是基础值；" % args.emotion)
        if "happy" in emo_map:
            hp = build_sampling_params(gpt, "happy", args.intensity)
            print("              happy 同强度下是 temperature=%.2f speed=%.2f top_k=%d，"
                  "想听就加 --emotion happy" % (hp["temperature"], hp["speed"], hp["top_k"]))
    print("输出目录      %s" % out_dir)
    print("=" * 72)

    texts = [args.text] if args.text else (list(ALL_TEXTS) if args.all else list(DEFAULT_TEXTS))
    cfg_value = str(cfg_streaming).strip().lower()
    cfg_streaming_on = cfg_value not in ("0", "false", "off", "")

    if args.replay:
        path = latest_wav(out_dir)
        if not path:
            raise SystemExit("还没有生成过 wav（%s）。先跑一次完整流程。" % out_dir)
        print("\n重放最近一次的结果：%s" % os.path.basename(path))
        pcm = read_wav_frames(path)
        if args.play and not args.play_file:
            print("           播放：生产处理（淡入 5ms + 淡出 %.0fms + 尾静音 %.0fms）"
                  % (args.fade_ms, args.tail_ms))
            play_raw(process_pcm(pcm, sr, fade_out_ms=args.fade_ms, tail_ms=args.tail_ms),
                     sr, tail_silence_ms=0)
        elif args.play:
            print("           播放：原始 wav（无淡出、无尾静音）")
            play(path)
        report, _ = analyze(pcm, gpt, sr)
        print_report("重放", report, path, [], 0.0, 0.0, sr)
        return

    jobs = []
    for text in texts:
        if args.ab:
            jobs.append((text, True))
            jobs.append((text, False))
        elif args.mode == "stream":
            jobs.append((text, True))
        elif args.mode == "nostream":
            jobs.append((text, False))
        else:
            jobs.append((text, cfg_streaming_on))

    results = {}
    index = 0
    for text, streaming in jobs:
        for round_idx in range(max(1, args.repeat)):
            index += 1
            label = "流式" if streaming else "非流式"
            payload = build_payload(text, gpt, ref, args.emotion, args.intensity,
                                    streaming, args.text_lang)
            print("\n[%d] %s  %r" % (index, label, text[:40]))
            if args.dry_run:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                continue
            wav_path = cache_path(out_dir, text, streaming, args.emotion, args.intensity, gpt, ref)
            cached = (not args.force) and os.path.exists(wav_path)
            if cached:
                print("           命中缓存（同样文本+参数），直接放；要重来得加 --force")
                pcm, sizes, first_sec, total_sec = read_wav_frames(wav_path), [], 0.0, 0.0
            else:
                sink = LiveSink(sr) if (args.live and args.play and not args.play_raw) else None
                if sink is not None and sink.proc is not None:
                    print("           边收边放：第一块到了就开始响，不整段等")
                try:
                    pcm, sizes, first_sec, total_sec = synth(
                        endpoint, payload, on_chunk=(sink.feed if sink else None))
                finally:
                    if sink is not None:
                        sink.close()
            if not pcm:
                print("           没收到音频（服务端异常，去看 logs/svc_sovits_*.log）")
                continue
            if not cached:
                write_wav(wav_path, pcm, sr)
            report, _ = analyze(pcm, gpt, sr)
            print_report(label, report, wav_path, sizes, first_sec, total_sec, sr)
            results.setdefault((text, label), []).append(report)
            if sink_done := (args.live and args.play and not args.play_raw and not cached):
                print("           播放：边收边放（已经放完）")
            elif args.play_file:
                print("           播放：原始 wav（无淡出、无尾静音，用来做对比）")
                play(wav_path)
            elif args.play:
                print("           播放：生产处理（淡入 5ms + 淡出 %.0fms + 尾静音 %.0fms）"
                      % (args.fade_ms, args.tail_ms))
                play_raw(process_pcm(pcm, sr, fade_out_ms=args.fade_ms,
                                     tail_ms=args.tail_ms), sr, tail_silence_ms=0)
            else:
                print("           --no-play：只存文件不播放")

    if args.ab and results and not args.dry_run:
        print("\n" + "=" * 72)
        print("对照结论（同一句，只看末段）")
        print("%-8s %8s %10s %12s %12s" % ("模式", "时长s", "末段跳变", "尖峰/常态", "尾部自相似"))
        for (text, label), reps in results.items():
            for rep in reps:
                sim = max((rep.get("tail_similarity") or {}).values() or [0.0])
                print("%-8s %8.2f %10.0f %12.1f %12.2f"
                      % (label, rep.get("sec", 0), rep.get("tail_jump", 0),
                         rep.get("tail_spike", 0), sim))
        print("\n尖峰倍数：< 5 正常；>= 8 说明末段有硬拼接（流式才有接缝，非流式没有）。")
        print("尾部自相似：语音一般 < 0.9；接近 1 且不是长元音，就是最后一小段被重放了。")
    elif not args.dry_run:
        print("\n尖峰倍数 < 5、自相似 < 0.9 就是干净；超过就带 wav 来对。")
    if not args.dry_run:
        print("wav 都在：%s   （再听一次：加 --replay，不重新合成）" % out_dir)


if __name__ == "__main__":
    main()
