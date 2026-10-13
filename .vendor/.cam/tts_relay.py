import base64
import threading
import time


class TtsRelay:
    """手机 TTS 中继：按 seq 缓冲 PCM，按模式过滤来源，meta 延迟回收"""

    def __init__(self, max_blocks=600, pending_limit=60, hold_secs=4.0,
                 max_pending_bytes=262144, max_block_bytes=16384):
        self._buf = []
        self._seq = 0
        self._meta = {}
        self._meta_id = 0
        self._last_block_ts = 0.0
        self._lock = threading.Lock()
        self._max_blocks = int(max_blocks)
        self._pending_limit = int(pending_limit)
        self._hold_secs = float(hold_secs)
        self._max_pending_bytes = int(max_pending_bytes)
        self._max_block_bytes = max(1024, int(max_block_bytes))
        self._mode = 'chat'
        self._dropping = False
        self._cur_source = ''
        self._filtered = 0
        self._log = []
        self._log_max = 40
        self._cur = None
        self._kept_traces = {}
        self._trace_ttl = 90.0
        self._running = True
        self._cleaner = threading.Thread(target=self._clean_loop, daemon=True, name='tts-relay')
        self._cleaner.start()

    def set_mode(self, mode):
        """切换 chat|call，并清空缓冲避免串台"""
        with self._lock:
            self._mode = 'call' if str(mode) == 'call' else 'chat'
            self._buf = []
            self._meta.clear()
            self._dropping = False
            self._cur_source = ''
            self._kept_traces.clear()
            self._last_block_ts = time.time()
            self._record('', '', True, note='mode->' + self._mode)

    def get_mode(self):
        """返回当前模式"""
        with self._lock:
            return self._mode

    def start_meta(self, meta):
        """标记新流开始；聊天模式下丢弃非 phone 来源（同轮回复的分段跟随首段保留）"""
        meta = meta or {}
        raw_src = meta.get('source')
        if raw_src is None or str(raw_src).strip() == '':
            # 旧版主项目推送时不带 source：该端点当时只服务手机音频，按 phone 处理
            source = 'phone'
            shown = 'phone*'
        else:
            source = str(raw_src).strip()
            shown = source
        traceid = str(meta.get('traceid') or '')
        # 通话模式：全部语音都转发给手机；聊天模式：只转发手机自己发起的对话
        keep = (self._mode == 'call') or (source == 'phone')
        with self._lock:
            self._expire_traces()
            if not keep and traceid and traceid in self._kept_traces:
                keep = True
            if keep and traceid:
                self._kept_traces[traceid] = time.time()
            self._cur_source = source
            self._dropping = not keep
            if not keep:
                self._filtered += 1
            self._cur = self._record(shown, str(meta.get('text') or ''), keep)
            if traceid:
                self._cur['traceid'] = traceid[:8]
            if not keep:
                return
            self._meta_id += 1
            self._meta.clear()
            self._meta.update(meta)
            self._meta['source'] = source
            self._meta['_id'] = self._meta_id
            self._meta['ended'] = False
            self._last_block_ts = time.time()

    def _expire_traces(self):
        """清理过期的"已保留 traceid"（调用方已持锁）"""
        now = time.time()
        for k in [k for k, v in self._kept_traces.items() if now - v > self._trace_ttl]:
            self._kept_traces.pop(k, None)

    def end_meta(self):
        """标记流结束；被过滤的流直接忽略"""
        rec = None
        with self._lock:
            if self._cur is not None:
                self._cur['end'] = True
                rec = self._cur
            if self._dropping:
                self._log_stream(rec)
                return
            if self._meta:
                self._meta['ended'] = True
                self._last_block_ts = time.time()
        self._log_stream(rec)

    def _log_stream(self, rec):
        """在 .phone 控制台打印一行，便于确认主项目有没有把语音推过来"""
        if not rec:
            return
        try:
            kb = (rec.get('bytes') or 0) / 1024.0
            print('[tts] mode=%s source=%s keep=%d %.1fKB %s'
                  % (rec.get('mode'), rec.get('source') or '-',
                     1 if rec.get('kept') else 0, kb,
                     (rec.get('text') or '')[:18]), flush=True)
        except Exception:
            pass

    def push(self, data):
        """追加 PCM（拆成小块）并分配单调递增 seq"""
        if not data:
            return
        with self._lock:
            if self._cur is not None:
                self._cur['bytes'] = int(self._cur.get('bytes', 0)) + len(data)
            if self._dropping:
                return
            self._last_block_ts = time.time()
            step = self._max_block_bytes
            for i in range(0, len(data), step):
                self._buf.append((self._seq, bytes(data[i:i + step])))
                self._seq += 1
            if len(self._buf) > self._max_blocks:
                del self._buf[:len(self._buf) - self._max_blocks]

    def pending(self, seq):
        """取 seq 之后的新块（同时受条数与字节上限约束）与当前 meta"""
        with self._lock:
            start = 0
            while start < len(self._buf) and self._buf[start][0] <= seq:
                start += 1
            items = []
            total = 0
            i = start
            while i < len(self._buf) and len(items) < self._pending_limit:
                s, d = self._buf[i]
                if items and (total + len(d)) > self._max_pending_bytes:
                    break
                items.append((s, d))
                total += len(d)
                i += 1
            blocks = [{'seq': s, 'pcm': base64.b64encode(d).decode('ascii')} for s, d in items]
            meta = {k: v for k, v in self._meta.items() if not str(k).startswith('_')}
            if items:
                next_seq = items[-1][0] + 1
            elif self._buf:
                next_seq = self._buf[-1][0] + 1
            else:
                next_seq = seq
            filtered = self._filtered
            self._filtered = 0
            return {'seq': next_seq, 'meta': meta, 'blocks': blocks, 'mid': self._meta_id,
                    'mode': self._mode, 'filtered': filtered,
                    'more': (start + len(items)) < len(self._buf)}

    def debug(self):
        """返回最近若干条流的处理记录，用于排查手机听到了什么"""
        with self._lock:
            return {
                'mode': self._mode,
                'seq': self._seq,
                'buffered_blocks': len(self._buf),
                'buffered_bytes': sum(len(d) for _, d in self._buf),
                'meta': {k: v for k, v in self._meta.items() if not str(k).startswith('_')},
                'log': list(self._log),
            }

    def stop(self):
        """停止清理线程"""
        self._running = False

    def _record(self, source, text, keep, note=''):
        """记录一条流（保留最近 N 条）"""
        rec = {'ts': round(time.time(), 2), 'mode': self._mode, 'source': source,
               'text': text[:60], 'kept': bool(keep), 'bytes': 0, 'blocks': 0, 'end': False,
               'traceid': ''}
        if note:
            rec['note'] = note
        self._log.append(rec)
        if len(self._log) > self._log_max:
            del self._log[:len(self._log) - self._log_max]
        return rec

    def _clean_loop(self):
        """静默超时后回收 meta，保证尾块仍可播放"""
        while self._running:
            time.sleep(0.5)
            with self._lock:
                if self._meta and (time.time() - self._last_block_ts) > self._hold_secs:
                    self._meta.clear()
