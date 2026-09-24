import queue
import threading
import time

import numpy as np
import requests


class AudioGateway:
    """手机麦克风网关：重采样 16k → 能量 VAD 分段 → 转发主项目 SenseVoice"""

    def __init__(self, api_base, target_rate=16000, frame_bytes=960, converter='sinc_medium',
                 energy_threshold=300.0, silence_secs=2.0, max_utterance_secs=30.0,
                 send_timeout=2.0, batch_secs=0.15, log=None):
        self._api = api_base.rstrip('/')
        self._rate = int(target_rate)
        self._frame_bytes = int(frame_bytes)
        self._converter = converter
        self._energy = float(energy_threshold)
        self._silence_secs = float(silence_secs)
        self._max_secs = float(max_utterance_secs)
        self._timeout = float(send_timeout)
        # 把 30ms 小帧攒成一批再 POST：请求数从 33/秒 降到 6~7/秒，抗主程序卡顿
        self._batch_secs = max(0.03, float(batch_secs or 0.15))
        self._log = log
        self._q = queue.Queue(maxsize=512)
        self._username = '手机用户'
        self._rate_in = 0
        self._channels = 1
        self._resampler = None
        self._lock = threading.Lock()
        self._sess = None
        self._running = True
        self.fails = 0
        self.dropped = 0
        self._worker = threading.Thread(target=self._loop, daemon=True, name='phone-audio')
        self._worker.start()

    def set_username(self, name):
        """设置当前手机用户名（随 /audio/send 透传）"""
        clean = (str(name) or '手机用户')[:20]
        if clean == self._username:
            return
        with self._lock:
            self._username = clean

    def feed(self, rate, channels, data, username=None):
        """接收手机上行原始 int16 PCM"""
        if not data:
            return
        if username:
            self.set_username(username)
        try:
            self._q.put_nowait((int(rate), int(channels), bytes(data)))
        except queue.Full:
            try:
                self._q.get_nowait()
                self._q.put_nowait((int(rate), int(channels), bytes(data)))
            except queue.Empty:
                pass
            self.dropped += 1

    def stop(self):
        """停止网关线程"""
        self._running = False

    def _session(self):
        """惰性创建 HTTP 会话"""
        if self._sess is None:
            self._sess = requests.Session()
        return self._sess

    def _post(self, path, data=None, params=None):
        """向主项目 POST，返回是否成功；失败累计（原来失败是静默丢弃，查不出问题）"""
        try:
            r = self._session().post(self._api + path, data=data, params=params,
                                     timeout=self._timeout)
            if r is not None and r.status_code >= 400:
                raise RuntimeError('http %d' % r.status_code)
            self.fails = 0
            return True
        except Exception:
            self.fails += 1
            if self._log and (self.fails == 1 or self.fails % 50 == 0):
                try:
                    self._log('[phone-audio] 上行失败 x%d（主程序 /audio/send 无响应？）' % self.fails)
                except Exception:
                    pass
            return False

    def _ensure_resampler(self, rate, channels):
        """按输入参数重建流式重采样器"""
        if rate == self._rate_in and channels == self._channels and (self._resampler is not None or rate == self._rate):
            return
        self._rate_in = int(rate)
        self._channels = max(1, int(channels))
        self._resampler = None
        if self._rate_in != self._rate:
            try:
                import samplerate
                self._resampler = samplerate.Resampler(self._converter, channels=1)
            except Exception:
                self._resampler = None

    def _convert(self, rate, channels, data):
        """int16 原生 PCM → 16k 单声道 int16 字节"""
        self._ensure_resampler(rate, channels)
        x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if self._channels > 1:
            usable = (len(x) // self._channels) * self._channels
            if usable <= 0:
                return b''
            x = x[:usable].reshape(-1, self._channels).mean(axis=1)
        if self._resampler is not None:
            x = self._resampler.process(x, self._rate / self._rate_in)
        if x is None or len(x) == 0:
            return b''
        return np.clip(x * 32768.0, -32768, 32767).astype(np.int16).tobytes()

    def _loop(self):
        """主循环：转换 → 切帧 → VAD → 批量上行"""
        pending = bytearray()
        speaking = False
        silence_frames = 0
        utter_frames = 0
        outbuf = bytearray()
        last_flush = time.time()
        silence_need = max(1, int(round(self._silence_secs * self._rate / (self._frame_bytes / 2))))
        utter_max = max(1, int(round(self._max_secs * self._rate / (self._frame_bytes / 2))))

        def flush(force=False):
            """把攒下的帧发出去（force=True 立即发，用于说话起点/结束）"""
            nonlocal outbuf, last_flush
            if not outbuf:
                last_flush = time.time()
                return
            if not force and (time.time() - last_flush) < self._batch_secs:
                return
            payload = bytes(outbuf)
            outbuf = bytearray()
            last_flush = time.time()
            try:
                self._post('/audio/send', data=payload, params={'username': self._username})
            except Exception:
                # 上行异常绝不允许弄死采集线程（原来一旦抛出，麦克风就彻底哑了）
                self.fails += 1

        def end_utterance():
            try:
                self._post('/audio/end', data=b'')
            except Exception:
                pass

        while self._running:
            try:
                rate, channels, data = self._q.get(timeout=0.05)
            except queue.Empty:
                flush()
                if speaking:
                    silence_frames += 1
                    if silence_frames >= silence_need or utter_frames >= utter_max:
                        flush(force=True)
                        end_utterance()
                        speaking = False
                        silence_frames = 0
                        utter_frames = 0
                        pending = bytearray()
                continue
            try:
                pending.extend(self._convert(rate, channels, data))
            except Exception:
                continue
            while len(pending) >= self._frame_bytes:
                frame = bytes(pending[:self._frame_bytes])
                del pending[:self._frame_bytes]
                energy = self._energy_of(frame)
                is_speech = energy >= self._energy
                if is_speech:
                    if not speaking:
                        speaking = True
                        utter_frames = 0
                        outbuf.extend(frame)
                        flush(force=True)     # 说话起点立刻发，别让 ASR 等批
                    else:
                        outbuf.extend(frame)
                    silence_frames = 0
                    utter_frames += 1
                elif speaking:
                    outbuf.extend(frame)
                    silence_frames += 1
                    utter_frames += 1
                if speaking and (silence_frames >= silence_need or utter_frames >= utter_max):
                    flush(force=True)
                    end_utterance()
                    speaking = False
                    silence_frames = 0
                    utter_frames = 0
                    pending = bytearray()
                elif speaking:
                    flush()
            # 连续失败太久 → 收尾，避免 ASR 挂在半句话上
            if self.fails >= 25 and speaking:
                end_utterance()
                speaking = False
                outbuf = bytearray()

    @staticmethod
    def _energy_of(frame):
        """计算 int16 帧的 RMS 能量"""
        a = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        if a.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(a ** 2)))
