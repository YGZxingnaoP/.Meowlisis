#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SenseVoice 识别延迟基准测试
============================================================
目的：实测「5 秒 / 10 秒 / 20 秒」语音从说完到被 SenseVoice 完整识别，
      分别要多久 —— 用于定位「识别本身慢」还是「等待环节慢」。

用法（用项目内置 Python 运行）：
    runtime\python.exe scripts\sensevoice_delay_bench.py --ping     # 连通性自检（不录音）
    runtime\python.exe scripts\sensevoice_delay_bench.py --list     # 只打印三句朗读文本
    runtime\python.exe scripts\sensevoice_delay_bench.py 5          # 录 5 秒，读第 1 句
    runtime\python.exe scripts\sensevoice_delay_bench.py 10         # 录 10 秒，读第 2 句
    runtime\python.exe scripts\sensevoice_delay_bench.py 20         # 录 20 秒，读第 3 句
    runtime\python.exe scripts\sensevoice_delay_bench.py            # 交互式选择

前置条件：
    1. 已启动 .SenseVoice 服务端（.SenseVoice\start.bat，监听 127.0.0.1:10095）
    2. 麦克风可用

输出口径：
    - 发送耗时    ：把音频全部推给服务端用了多久（本脚本快速发送，接近 0）
    - 识别延迟    ：服务端收到全部音频+「我说完了」信号 → 返回识别文本 的耗时（核心指标）
    - 总耗时      ：按下录音 → 收到识别结果
结果会追加保存到 scripts/sensevoice_bench_results.txt
"""

import argparse
import asyncio
import json
import os
import sys
import time
import datetime

# Windows 控制台 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RATE = 16000                 # 采样率
CHUNK_MS = 400               # 与 config.yml sensevoice.chunk_size_ms 对齐
FRAME_BYTES = RATE * CHUNK_MS // 1000 * 2   # 400ms * 16k * 2字节 = 12800 字节/帧

SERVER_URL = os.environ.get("SV_URL", "ws://127.0.0.1:10095/")
RESULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensevoice_bench_results.txt")

# ==================== 三句朗读文本（中性、无角色，正常语速） ====================
SENTENCES = {
    5: "今天天气晴朗，气温适中，很适合出门散步。",
    10: "充足的睡眠对记忆力很有帮助，人在睡觉时，大脑会把白天学到的东西"
        "整理成长期记忆，所以好好休息非常重要。",
    20: "根据气象预报，未来三天全国大部分地区将明显降温，部分地区最低气温"
        "将下降八到十摄氏度。气象部门提醒大家及时增添衣物，预防感冒，老人"
        "和儿童尽量减少早晚外出，出行请注意安全。",
}


def print_sentences():
    print("请朗读以下句子（匀速、自然，说完停住即可）：\n")
    for secs, text in SENTENCES.items():
        print(f"【{secs} 秒】预计 {len(text)} 字\n    {text}\n")


def record(seconds: int) -> bytes:
    """用麦克风录制 seconds 秒 16k 单声道 int16 PCM"""
    import pyaudio
    pa = pyaudio.PyAudio()
    try:
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE,
                         input=True, frames_per_buffer=int(RATE * 0.1))
        chunks = []
        total_frames = int(RATE * seconds / (RATE * 0.1))
        print(f"🎤 录音中… {seconds} 秒，请现在开始朗读：")
        for _ in range(total_frames):
            chunks.append(stream.read(int(RATE * 0.1), exception_on_overflow=False))
        stream.stop_stream()
        stream.close()
    finally:
        pa.terminate()
    return b"".join(chunks)


async def send_and_measure(audio: bytes, seconds: int) -> dict:
    """连接服务端：发说话开始 → 快速发完全部音频 → 发说话结束 → 等识别结果"""
    import websockets

    t_rec_end = time.perf_counter()
    t_send_start = t_rec_end
    final_text = ""
    final_mode = ""
    spk = ""

    async with websockets.connect(SERVER_URL, ping_interval=None,
                                  subprotocols=["binary"]) as ws:
        # 1) 告诉服务端：开始说话（新连接 buffer 为空，直接 true）
        await ws.send(json.dumps({
            "is_speaking": True, "wav_name": "bench",
            "language": "auto", "itn": True, "hotwords": {},
        }))
        # 2) 分帧发送全部音频
        for i in range(0, len(audio), FRAME_BYTES):
            await ws.send(audio[i:i + FRAME_BYTES])
        # 3) 告诉服务端：说完了 → 触发识别
        await ws.send(json.dumps({"is_speaking": False}))
        t_send_end = time.perf_counter()

        # 4) 等待最终识别结果
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=60)
            try:
                obj = json.loads(msg)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            text = (obj.get("text") or "").strip()
            is_final = bool(obj.get("is_final")) or (obj.get("mode") == "offline")
            if text and is_final:
                final_text = text
                final_mode = str(obj.get("mode", ""))
                spk = str(obj.get("spk_name", ""))
                break
        t_final = time.perf_counter()

    return {
        "audio_secs": seconds,
        "audio_bytes": len(audio),
        "send_duration": t_send_end - t_send_start,      # 推流耗时（本脚本≈0）
        "recog_delay": t_final - t_send_end,             # 说完→识别结果（核心）
        "total": t_final - t_rec_end,                    # 发送开始→结果
        "text": final_text,
        "mode": final_mode,
        "spk": spk,
    }


async def ping_server() -> bool:
    """连通性自检：发 1 秒静音，验证服务端在线并返回识别结果"""
    import websockets
    silence = b"\x00" * (RATE * 1 * 2)   # 1 秒静音
    try:
        async with websockets.connect(SERVER_URL, ping_interval=None,
                                      subprotocols=["binary"]) as ws:
            await ws.send(json.dumps({
                "is_speaking": True, "wav_name": "bench",
                "language": "auto", "itn": True, "hotwords": {},
            }))
            for i in range(0, len(silence), FRAME_BYTES):
                await ws.send(silence[i:i + FRAME_BYTES])
            await ws.send(json.dumps({"is_speaking": False}))
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                obj = json.loads(msg)
                if isinstance(obj, dict) and obj.get("is_final"):
                    print(f"✅ 服务端在线并返回: '{obj.get('text', '')}' "
                          f"(说话人={obj.get('spk_name')})")
                    return True
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print("   请确认 .SenseVoice 服务端已启动（.SenseVoice\\start.bat）")
        return False


def save_result(seconds: int, r: dict):
    try:
        with open(RESULT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] "
                    f"时长={seconds}s 识别延迟={r['recog_delay']:.2f}s "
                    f"发送={r['send_duration']:.2f}s 总={r['total']:.2f}s | "
                    f"文本={r['text'][:40]}\n")
    except Exception:
        pass


async def main():
    ap = argparse.ArgumentParser(description="SenseVoice 识别延迟基准测试")
    ap.add_argument("seconds", nargs="?", type=int, choices=[5, 10, 20],
                    help="录音时长秒数: 5/10/20")
    ap.add_argument("--ping", action="store_true", help="连通性自检（不录音）")
    ap.add_argument("--list", action="store_true", help="只打印朗读文本")
    args = ap.parse_args()

    if args.list:
        print_sentences()
        return

    if args.ping:
        ok = await ping_server()
        sys.exit(0 if ok else 1)

    seconds = args.seconds
    if seconds is None:
        print_sentences()
        try:
            seconds = int(input("输入录音秒数 [5/10/20]: ").strip())
        except Exception:
            seconds = 5
        if seconds not in (5, 10, 20):
            seconds = 5

    print_sentences()
    print(f"你将朗读【{seconds} 秒】对应的句子。按回车后 3 秒开始录音。")
    try:
        input()
    except Exception:
        pass
    print("3")
    await asyncio.sleep(1)
    print("2")
    await asyncio.sleep(1)
    print("1")
    await asyncio.sleep(1)

    audio = record(seconds)
    print(f"\n✅ 录音完成: {len(audio)} 字节 ≈ {len(audio)/RATE/2:.1f} 秒\n"
          f"📤 连接 {SERVER_URL} 并发送识别…")

    try:
        r = await send_and_measure(audio, seconds)
    except Exception as e:
        print(f"❌ 识别失败: {e}")
        sys.exit(1)

    print("\n==================== 测试结果 ====================")
    print(f"音频时长      : {r['audio_secs']} 秒（实际 {r['audio_bytes']/RATE/2:.1f}s）")
    print(f"音频推流耗时  : {r['send_duration']*1000:.0f} ms")
    print(f"【识别延迟】  : {r['recog_delay']:.2f} 秒   ← 说完到出结果")
    print(f"总耗时(发送起): {r['total']:.2f} 秒")
    print(f"识别文本      : {r['text']}")
    print(f"识别模式      : {r['mode']}  说话人={r['spk']}")
    print("==================================================\n")
    if r["text"]:
        print(f"（文本长度 {len(r['text'])} 字，可对照原文看识别完整度）\n")
    save_result(seconds, r)


if __name__ == "__main__":
    asyncio.run(main())
