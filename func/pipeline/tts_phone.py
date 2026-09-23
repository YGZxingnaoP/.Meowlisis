# -*- coding: utf-8 -*-
# func/pipeline/tts_phone.py - 手机 TTS 播放通道
# 主项目 TTS 播放线程把 PCM 交给本模块，转发到 .phone 服务（手机实时播放）。
# 纯旁路：本机网络故障/慢只丢手机音频，不影响主项目任何环节。
#
# 线程模型：播放线程只"入队"（快）；发送线程单线消费——
#   - start/end/data 走【同一个队列】，严格保序（start 必先于其数据块，end 必后于其数据块）；
#   - 数据块积压超限则丢弃【新到】的数据块（标记永不丢，音频实时性优先）。

import queue
import threading
import time

# .phone 手机服务接收端点（.phone/serve.py 固定 HTTPS 端口 8443，自签名证书）
PHONE_TTS_URL = "https://127.0.0.1:8443/api/tts/phone"


class TtsPhoneBridge:
    """把手机侧 TTS 音频转发给 .phone：单队列严格保序 + 独立发送线程"""

    def __init__(self, url: str = PHONE_TTS_URL, max_pending: int = 256):
        self.url = url
        self._max_data = max(16, int(max_pending))
        self._q = queue.Queue()
        self._n_data = 0
        self._stop = threading.Event()
        self._sess = None
        self._fail_logged = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._worker, daemon=True,
                                        name="tts-phone")
        self._thread.start()

    # ---------- 主播放线程调用（只入队，绝不阻塞/网络 IO） ----------
    def start_stream(self, text: str = "", traceid: str = "",
                     sample_rate: int = 32000, source: str = "", seg_index: int = 0):
        """标记一句话开始，并带上来源与分段号供 .phone 过滤/分句显示"""
        self._put(("start", {"text": text, "traceid": traceid,
                             "sample_rate": int(sample_rate or 32000),
                             "source": str(source or ""),
                             "seg_index": int(seg_index or 0)}))

    def push(self, data: bytes):
        """推一块 PCM 音频（播放线程每 pop 一块调用）"""
        if not data:
            return
        self._put(("data", bytes(data)))

    def end_stream(self):
        """标记一句话结束"""
        self._put(("end", None))

    def close(self):
        """停止发送线程（进程退出时调用）"""
        self._stop.set()
        self._put(("end", None))

    # ---------- 入队 ----------
    def _put(self, item):
        """入队；数据块超过积压上限时丢弃新块（标记永不丢）"""
        if item[0] == "data":
            with self._lock:
                if self._n_data >= self._max_data:
                    return
                self._n_data += 1
        try:
            self._q.put_nowait(item)
        except Exception:
            if item[0] == "data":
                with self._lock:
                    self._n_data = max(0, self._n_data - 1)

    # ---------- 发送线程：单队列 FIFO，事件与数据严格保序 ----------
    def _session(self):
        if self._sess is None:
            import requests
            requests.packages.urllib3.disable_warnings()
            self._sess = requests.Session()
        return self._sess

    def _post(self, params=None, data=None, json=None):
        try:
            self._session().post(self.url, params=params, data=data, json=json,
                                 timeout=1.0, verify=False)
        except Exception as e:
            if not self._fail_logged:
                self._fail_logged = True
                try:
                    import logging
                    logging.getLogger("tts_phone").warning(
                        "[tts_phone] 手机音频通道不可达（.phone 未启动？）：%s", e)
                except Exception:
                    pass

    def _worker(self):
        buf = []
        last_flush = time.time()
        while not self._stop.is_set():
            try:
                kind, payload = self._q.get(timeout=0.05)
            except queue.Empty:
                kind, payload = None, None
            now = time.time()

            if kind == "data":
                with self._lock:
                    self._n_data = max(0, self._n_data - 1)
                buf.append(payload)
            elif kind == "start":
                self._flush(buf)
                buf = []
                self._post(params={"start": "1"}, json=payload or {})
                last_flush = now
            elif kind == "end":
                self._flush(buf)
                buf = []
                self._post(params={"end": "1"})
                last_flush = now

            if buf and (len(buf) >= 24 or now - last_flush >= 0.25):
                self._flush(buf)
                buf = []
                last_flush = now

    def _flush(self, chunk_buf):
        """把攒下的 PCM 块合并为一次 POST（body=连续 PCM 字节）"""
        if not chunk_buf:
            return
        self._post(data=b"".join(chunk_buf))
