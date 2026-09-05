# -*- coding: utf-8 -*-
# func/pipeline/tts_phone.py - 手机 TTS 播放通道
# 主项目 TTS 播放线程把 source=phone 的流式 PCM 交给本模块，转发到 .phone 服务
# （手机实时播放）。纯旁路：本机网络故障/慢只丢手机音频，不影响主项目任何环节。
#
# 线程模型：播放线程只做"入队"（快）；发送线程单线消费——
#   - 事件（start/end）走独立高优队列，保证句子边界严格有序、不因块积压丢失；
#   - PCM 块走块队列（有界，满则丢最旧：音频实时性优先）。

import queue
import threading
import time

# .phone 手机服务接收端点（.phone/serve.py 固定 HTTPS 端口 8443，自签名证书）
PHONE_TTS_URL = "https://127.0.0.1:8443/api/tts/phone"


class TtsPhoneBridge:
    """把 phone 任务的 TTS 音频转发给手机：独立发送线程 + 有界队列"""

    def __init__(self, url: str = PHONE_TTS_URL, max_pending: int = 256):
        self.url = url
        self._ev_q = queue.Queue(maxsize=16)      # 事件：(kind, payload)
        self._ch_q = queue.Queue(maxsize=max_pending)  # PCM 块（可丢）
        self._stop = threading.Event()
        self._sess = None
        self._thread = threading.Thread(target=self._worker, daemon=True,
                                        name="tts-phone")
        self._thread.start()

    # ---------- 主播放线程调用（只入队，绝不阻塞/网络） ----------
    def start_stream(self, text: str = "", traceid: str = "",
                     sample_rate: int = 32000):
        """标记一句话开始（播放线程进入 phone 流前调用）"""
        self._put_event(("start", {"text": text, "traceid": traceid,
                                   "sample_rate": int(sample_rate or 32000)}))

    def push(self, data: bytes):
        """推一块 PCM 音频（播放线程每 pop 一块调用）"""
        if not data:
            return
        try:
            self._ch_q.put_nowait(bytes(data))
        except queue.Full:
            # 队列满：丢最旧一块，保证实时性
            try:
                self._ch_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._ch_q.put_nowait(bytes(data))
            except queue.Full:
                pass

    def end_stream(self):
        """标记一句话结束"""
        self._put_event(("end", None))

    def _put_event(self, ev):
        """事件入队；几乎不会满，极端满时丢弃最旧事件（保最新边界）"""
        try:
            self._ev_q.put_nowait(ev)
        except queue.Full:
            try:
                self._ev_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._ev_q.put_nowait(ev)
            except queue.Full:
                pass

    def close(self):
        """停止发送线程（进程退出时调用）"""
        self._stop.set()
        try:
            self._ev_q.put_nowait(("end", None))
        except queue.Full:
            pass

    # ---------- 发送线程：事件优先，PCM 攒批推送 ----------
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
        except Exception:
            pass

    def _worker(self):
        chunk_buf = []
        last_flush = 0.0
        while not self._stop.is_set():
            now = time.time()

            # 1) 事件高优：先消费干净（保证 start 早于块、end 收尾）
            try:
                kind, payload = self._ev_q.get_nowait()
            except queue.Empty:
                kind = None
            if kind == "start":
                self._flush(chunk_buf)
                chunk_buf = []
                self._post(params={"start": "1"}, json=payload or {})
            elif kind == "end":
                self._flush(chunk_buf)
                chunk_buf = []
                self._post(params={"end": "1"})

            # 2) 取一块入攒批缓冲（阻塞短超时兜底）
            try:
                c = self._ch_q.get(timeout=0.05)
            except queue.Empty:
                c = None
            if c:
                chunk_buf.append(c)

            # 3) 攒批达量/达时即推送（0.25s 或 24 块）
            if chunk_buf and (len(chunk_buf) >= 24 or now - last_flush >= 0.25):
                self._flush(chunk_buf)
                chunk_buf = []
                last_flush = now

    def _flush(self, chunk_buf):
        """把攒下的 PCM 块合并为一次 POST（body=连续 PCM 字节）"""
        if not chunk_buf:
            return
        self._post(data=b"".join(chunk_buf))
