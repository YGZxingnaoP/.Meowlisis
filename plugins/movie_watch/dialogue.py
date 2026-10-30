# -*- coding: utf-8 -*-
"""台词采集：扬声器回环 → SenseVoice 服务 → 台词文本。

完全自包含，不 import 主项目任何代码：
- 采集：pyaudiowpatch（WASAPI loopback）+ numpy 降混/重采样到 16k 单声道；
- 传输：websockets 直连 FunASR 的在线识别协议（config → 音频帧 → JSON 结果）；
- 判停：自己算 RMS 能量做 VAD，决定 is_speaking；
- 服务地址/语言/停顿阈值：只按 YAML 读主程序 config.yml 的 sensevoice 节点（数据，不是代码）。
"""

import asyncio
import json
import queue
import re
import socket
import threading
import time
from collections import deque
from urllib.parse import urlparse

import numpy as np
import yaml


def read_yaml(path):
    try:
        with open(str(path), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _host_port(url):
    try:
        parsed = urlparse(str(url))
        return parsed.hostname or "", int(parsed.port or 10095)
    except Exception:
        return "", 0


# ==================== 扬声器回环 ====================
class LoopbackCapture:
    """WASAPI 回环采集：固定输出 16k 单声道 int16、每帧 300ms。"""

    FRAME_MS = 300

    def __init__(self, log, device_index=-1, target_rate=16000):
        self.log = log
        self.device_index = int(device_index)
        self.target_rate = int(target_rate)
        self._pa = None
        self._stream = None
        self._rate = 48000
        self._channels = 2
        self._buf = np.zeros(0, dtype=np.float32)
        self._chunk = int(self.target_rate * self.FRAME_MS / 1000)

    # ---------- 设备 ----------
    @staticmethod
    def list_devices():
        try:
            import pyaudiowpatch as pyaudio
        except Exception:
            return []
        devices = []
        pa = pyaudio.PyAudio()
        try:
            for info in pa.get_loopback_device_info_generator():
                devices.append({"index": int(info.get("index", 0)),
                                "name": info.get("name", ""),
                                "channels": int(info.get("maxInputChannels", 0)),
                                "rate": int(info.get("defaultSampleRate", 0))})
        except Exception:
            pass
        finally:
            pa.terminate()
        return devices

    def _pick_device(self, pa):
        if self.device_index >= 0:
            try:
                return pa.get_device_info_by_index(self.device_index)
            except Exception:
                pass
        try:
            import pyaudiowpatch as mod
            wasapi = getattr(mod, "paWASAPI", 13)
        except Exception:
            wasapi = 13
        try:
            host = pa.get_host_api_info_by_type(wasapi)
            default = pa.get_device_info_by_index(host["defaultOutputDevice"])
            name = str(default.get("name") or "")
            for loopback in pa.get_loopback_device_info_generator():
                if name and name in str(loopback.get("name") or ""):
                    return loopback
            return default
        except Exception:
            for loopback in pa.get_loopback_device_info_generator():
                return loopback
        raise RuntimeError("没找到可用的扬声器回环设备")

    # ---------- 生命周期 ----------
    def open(self):
        import pyaudiowpatch as pyaudio
        self._pa = pyaudio.PyAudio()
        device = self._pick_device(self._pa)
        self._rate = int(device.get("defaultSampleRate") or 48000)
        self._channels = max(1, int(device.get("maxInputChannels") or 2))
        frames = max(1, int(round(self._rate * self.FRAME_MS / 1000.0)))
        self._stream = self._pa.open(
            format=pyaudio.paInt16, channels=self._channels, rate=self._rate,
            input=True, input_device_index=int(device.get("index")),
            frames_per_buffer=frames)
        self._buf = np.zeros(0, dtype=np.float32)
        self.log.info(f"[movie_watch] 回环设备：{device.get('name')} "
                      f"{self._rate}Hz/{self._channels}ch → 16k 单声道")
        return True

    def close(self, timeout=1.2):
        """关设备：WASAPI 空闲时读线程可能卡在 read()，所以关闭放到子线程并限时等待"""
        worker = threading.Thread(target=self._close_now, daemon=True,
                                  name="movie-loopback-close")
        worker.start()
        worker.join(timeout)
        return not worker.is_alive()

    def _close_now(self):
        stream, pa = self._stream, self._pa
        self._stream, self._pa = None, None
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass

    # ---------- 读帧 ----------
    def _resample(self, data):
        if self._rate == self.target_rate:
            return data
        try:
            from math import gcd
            from scipy.signal import resample_poly
            step = gcd(self._rate, self.target_rate)
            return resample_poly(data, self.target_rate // step, self._rate // step)
        except Exception:
            count = int(round(len(data) * self.target_rate / self._rate))
            if count <= 1:
                return np.zeros(0, dtype=np.float32)
            return np.interp(np.linspace(0, len(data) - 1, count),
                             np.arange(len(data)), data)

    def read(self):
        """返回 16k 单声道 int16 的 300ms 帧；不足一帧返回 None"""
        if self._stream is None:
            return None
        frames = max(1, int(round(self._rate * self.FRAME_MS / 1000.0)))
        raw = self._stream.read(frames, exception_on_overflow=False)
        if not raw:
            return None
        samples = np.frombuffer(raw, dtype=np.int16)
        if samples.size == 0:
            return None
        if self._channels > 1:
            usable = samples.size - samples.size % self._channels
            samples = samples[:usable].reshape(-1, self._channels).mean(axis=1)
        audio = self._resample(samples.astype(np.float32))
        self._buf = np.concatenate([self._buf, audio]) if self._buf.size else audio
        if self._buf.size < self._chunk:
            return None
        chunk = self._buf[:self._chunk]
        self._buf = self._buf[self._chunk:]
        return np.clip(chunk, -32768, 32767).astype(np.int16).tobytes()


def rms_of(frame):
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


# ==================== 能量 VAD ====================
class EnergyVad:
    """RMS 能量判停：超过阈值算说话，静音超过 N 秒算说完"""

    def __init__(self, threshold=300.0, silence_seconds=2.0):
        self.threshold = float(threshold)
        self.silence_seconds = float(silence_seconds)
        self.speaking = False
        self._quiet_since = None

    def update(self, frame):
        level = rms_of(frame)
        now = time.time()
        if level >= self.threshold:
            self._quiet_since = None
            if not self.speaking:
                self.speaking = True
                return "started"
            return None
        if self.speaking:
            if self._quiet_since is None:
                self._quiet_since = now
            elif now - self._quiet_since >= self.silence_seconds:
                self.speaking = False
                self._quiet_since = None
                return "stopped"
        return None


# ==================== 台词会话 ====================
class DialogueListener:
    """一条独立的「听电脑声音」识别会话，产出带时间戳的台词句。"""

    CONNECT_RETRY = 10
    SENTENCE_KEEP = 200

    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.detail = "未启用"
        self.ready = False
        self.active = False
        self._thread = None
        self._running = False
        self._capture = None
        self._frames = queue.Queue(maxsize=64)
        self._sentences = deque(maxlen=self.SENTENCE_KEEP)
        self._lock = threading.Lock()
        self._suppress_until = 0.0
        self._peak = 0.0            # 回环听到过的最大 RMS（开播前用它确认「电脑在出声」）

    # ==================== 前置检查 ====================
    def _asr_node(self):
        node = read_yaml(self.config.project_config).get("sensevoice") or {}
        return node if isinstance(node, dict) else {}

    def preflight(self):
        """能不能用：开关、依赖、识别服务可达性"""
        if not self.config.dialogue_enabled:
            self.detail = "未启用（配置里关掉了台词识别）"
            return False
        try:
            import pyaudiowpatch  # noqa: F401
        except Exception:
            self.detail = "没装 pyaudiowpatch，读不到电脑声音"
            return False
        try:
            import websockets  # noqa: F401
        except Exception:
            self.detail = "没装 websockets，连不上识别服务"
            return False
        node = self._asr_node()
        if not node.get("enabled", True):
            self.detail = "主程序 sensevoice.enabled 是关的"
            return False
        url = self.config.dialogue_server or node.get("server_url") or "ws://127.0.0.1:10095/"
        host, port = _host_port(url)
        if not host:
            self.detail = f"识别服务地址不合法：{url}"
            return False
        try:
            sock = socket.create_connection((host, port), timeout=1.5)
            sock.close()
        except Exception:
            self.detail = f"识别服务没启动（{host}:{port}）"
            return False
        self.ready = True
        self.detail = f"台词识别就绪（{host}:{port}）"
        return True

    # ==================== 生命周期 ====================
    def start(self):
        if self.active or not self.ready:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="movie-dialogue")
        self._thread.start()
        self.active = True
        return True

    def stop(self):
        self._running = False
        capture = self._capture
        if capture is not None:
            threading.Thread(target=self._safe_close, args=(capture,), daemon=True).start()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)
        self.active = False
        self._capture = None
        self._drain()

    def suppress_for(self, seconds):
        """自己刚说过话：这段时间别听自己"""
        self._suppress_until = max(self._suppress_until, time.time() + float(seconds))

    def wait_audio(self, seconds=2.5, threshold=80.0):
        """试听一小段：听到超过阈值就提前返回，最终返回这段时间的回环峰值 RMS"""
        deadline = time.time() + max(0.3, float(seconds))
        while time.time() < deadline:
            if self._peak >= float(threshold):
                break
            time.sleep(0.1)
        return self._peak

    @staticmethod
    def _safe_close(capture):
        try:
            capture.close()
        except Exception:
            pass

    def _drain(self):
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return

    # ==================== 台词读取 ====================
    def window_text(self, seconds=None, max_chars=None):
        """最近 N 秒的台词，拼成一段（超出字数从最早开始丢）"""
        seconds = int(seconds or self.config.dialogue_window)
        max_chars = int(max_chars or self.config.dialogue_chars)
        deadline = time.time() - max(5, seconds)
        with self._lock:
            items = [item for item in self._sentences if item["ts"] >= deadline]
        if not items or max_chars <= 0:
            return ""
        picked = []
        total = 0
        for item in reversed(items):
            text = item["text"]
            if total + len(text) > max_chars and picked:
                break
            picked.append(text)
            total += len(text)
        picked.reverse()
        return "；".join(picked)[-max_chars:]

    def sentence_count(self):
        with self._lock:
            return len(self._sentences)

    def _add_sentence(self, text, speaker=""):
        text = str(text or "").strip()
        if len(text) < 2:
            return
        with self._lock:
            if self._sentences and self._sentences[-1]["text"] == text:
                return
            if self._sentences and self._sentences[-1]["text"].endswith(text):
                return
            self._sentences.append({"ts": time.time(), "text": text, "who": speaker})

    # ==================== 采集 + 识别线程 ====================
    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._service())
        except Exception:
            self.log.exception("[movie_watch] 台词识别线程异常")
        finally:
            self._running = False
            self.active = False
            capture = self._capture
            self._capture = None
            if capture is not None:
                self._safe_close(capture)
            try:
                loop.close()
            except Exception:
                pass

    async def _service(self):
        import websockets

        node = self._asr_node()
        url = self.config.dialogue_server or node.get("server_url") or "ws://127.0.0.1:10095/"
        threshold = (getattr(self.config, "dialogue_vad_threshold", 0)
                     or node.get("vad_energy_threshold") or 300)
        vad = EnergyVad(threshold=float(threshold),
                        silence_seconds=float(node.get("silence_threshold") or 2.0))
        start_cfg = {
            "wav_name": "movie",
            "is_speaking": False,
            "language": str(node.get("language") or "auto"),
            "itn": bool(node.get("itn", True)),
            "mode": str(node.get("mode") or "2pass"),
        }
        failures = 0
        while self._running:
            try:
                async with websockets.connect(
                        url, subprotocols=["binary"],
                        ping_interval=int(node.get("ping_interval") or 20),
                        ping_timeout=int(node.get("ping_timeout") or 30),
                        max_size=None) as ws:
                    failures = 0
                    self.detail = "台词识别已连接"
                    self.log.info(f"[movie_watch] 台词识别已连接（{url}）")
                    await ws.send(json.dumps(start_cfg, ensure_ascii=False))
                    await asyncio.gather(self._pump(ws, vad), self._recv(ws))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                failures += 1
                if not self._running:
                    break
                if failures > self.CONNECT_RETRY:
                    self.detail = f"台词识别连不上：{e}"
                    self.log.warning(f"[movie_watch] 台词识别放弃重连：{e}")
                    break
                self.detail = f"台词识别重连中（{failures}/{self.CONNECT_RETRY}）"
                await asyncio.sleep(3)

    async def _pump(self, ws, vad):
        """读回环 → 能量 VAD → 送服务端；回环没数据时送静音占位

        电影声音里背景音乐常年高于能量阈值，VAD 很难自然「说完」，
        所以再加一道强制分句：连续说话超过 segment_seconds 就主动断一次句，
        让服务端交出这一段 final 文本。
        """
        opened = await asyncio.to_thread(self._open_capture)
        if not opened:
            raise RuntimeError(self.detail or "扬声器回环打不开")
        silence = b"\x00" * (int(16000 * LoopbackCapture.FRAME_MS / 1000) * 2)
        segment = float(getattr(self.config, "dialogue_segment_seconds", 8) or 0)
        warned = False
        last_data = time.time()
        last_boundary = time.time()
        while self._running:
            frame = await asyncio.to_thread(self._next_frame, 1.0)
            if frame is None:
                if time.time() - last_data > 8 and not warned:
                    warned = True
                    self.detail = "台词识别已连接（回环暂时没声音）"
                    self.log.info("[movie_watch] 回环暂时没数据，继续等播放")
                frame = silence
            else:
                last_data = time.time()
                warned = False
                level = rms_of(frame)
                if level > self._peak:
                    self._peak = level
            if time.time() < self._suppress_until:
                frame = silence
            event = vad.update(frame)
            if event == "started":
                await ws.send(json.dumps({"is_speaking": True}))
                last_boundary = time.time()
            elif event == "stopped":
                await ws.send(json.dumps({"is_speaking": False}))
                last_boundary = time.time()
            elif (segment > 0 and vad.speaking
                  and time.time() - last_boundary >= segment):
                # 连续说话太久：主动断句，让服务端把这一段交出来
                await ws.send(json.dumps({"is_speaking": False}))
                await asyncio.sleep(0.05)
                await ws.send(json.dumps({"is_speaking": True}))
                last_boundary = time.time()
            await ws.send(frame if vad.speaking else silence)
            await asyncio.sleep(0.01)

    async def _recv(self, ws):
        async for message in ws:
            if not self._running:
                break
            text, speaker = self._extract(message)
            if text:
                self._add_sentence(text, speaker)

    @staticmethod
    def _extract(message):
        """从服务端消息里取最终文本（partial 不要，避免重复）"""
        if isinstance(message, bytes):
            return "", ""
        try:
            data = json.loads(message)
        except Exception:
            return "", ""
        text = str(data.get("text") or "")
        if not text:
            return "", ""
        is_final = bool(data.get("is_final"))
        mode = str(data.get("mode") or "")
        if not (is_final or "offline" in mode):
            return "", ""
        text = re.sub(r"<\|.*?\|>", "", text).strip()
        speaker = str(data.get("spk_name") or "").strip()
        if speaker in ("未知", "unknown", "None", "null"):
            speaker = ""
        return text, speaker

    # ==================== 回环设备 ====================
    def _open_capture(self):
        try:
            capture = LoopbackCapture(self.log, device_index=self.config.dialogue_device)
            capture.open()
        except Exception as e:
            self.detail = f"扬声器回环打不开：{e}"
            self.log.warning(f"[movie_watch] {self.detail}")
            return False
        self._capture = capture
        self._drain()
        threading.Thread(target=self._reader_loop, args=(capture,), daemon=True,
                         name="movie-dialogue-cap").start()
        return True

    def _reader_loop(self, capture):
        """阻塞读设备（WASAPI 空闲时会阻塞，所以独立线程 + 队列）"""
        while self._running:
            try:
                frame = capture.read()
            except Exception:
                break
            if not frame:
                time.sleep(0.02)
                continue
            try:
                self._frames.put_nowait(frame)
            except queue.Full:
                pass

    def _next_frame(self, timeout):
        try:
            return self._frames.get(timeout=timeout)
        except queue.Empty:
            return None
