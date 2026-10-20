import base64
import collections
import hashlib
import json
import struct
import threading
import time

WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BIN = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

SUB_VIDEO = 0x01
SUB_AUDIO = 0x02
SUB_AUDIO_MON = 0x03

# 心跳默认值（serve.py 用 config.py 里的配置传入）
PING_IDLE_SECS = 15.0
PONG_TIMEOUT_SECS = 60.0
KEEP_INTERVAL_SECS = 5.0


def compute_accept(key):
    """计算 Sec-WebSocket-Accept"""
    raw = (str(key or '') + WS_GUID).encode('utf-8')
    return base64.b64encode(hashlib.sha1(raw).digest()).decode('ascii')


def _recv_exact(sock, n):
    """从 socket 精确读取 n 字节，断连返回 None"""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except Exception:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _encode_frame(opcode, payload):
    """构造服务端→客户端的 WebSocket 帧"""
    header = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        header += bytes([n])
    elif n < 65536:
        header += bytes([126]) + struct.pack('>H', n)
    else:
        header += bytes([127]) + struct.pack('>Q', n)
    return header + payload


class WsConn:
    """单条 WebSocket 连接：分帧收发 + 独立发送锁 + 有界发送队列（丢旧不堵上行）"""

    # 每个 viewer 的发送队列上限（帧）：满了丢最旧的，绝不阻塞手机上行线程
    Q_MAX = 24

    def __init__(self, sock):
        self._sock = sock
        self._send_lock = threading.Lock()
        self.alive = True
        self.role = None
        self.username = ''
        self.audio_rate = 48000
        self.audio_ch = 1
        self.audio_on = True
        self._frag_op = None
        self._frag_buf = bytearray()
        # 有界发送队列（只在 viewer 下行方向使用）
        self._cv = threading.Condition()
        self._q = collections.deque()
        self.dropped = 0
        self._sender = None
        # 心跳/半开连接判定：手机被系统杀掉不会发 FIN，只有靠 ping/pong 超时才能回收
        self.created = time.time()
        self.last_rx = self.created
        self.last_ping = 0.0

    # ---------- 异步发送（防慢客户端拖死上行） ----------
    def start_sender(self):
        """启动发送线程：所有下行媒体帧都走队列"""
        if self._sender is not None:
            return
        self._sender = threading.Thread(target=self._send_loop, daemon=True, name='ws-send')
        self._sender.start()

    def _send_loop(self):
        while True:
            with self._cv:
                while not self._q and self.alive:
                    self._cv.wait(0.5)
                if not self.alive:
                    return
                payload = self._q.popleft()
            if not self._send(OP_BIN, payload):
                return

    def enqueue_bin(self, payload):
        """入队一帧媒体数据；队列满丢最旧。返回 True 表示发生了丢弃"""
        with self._cv:
            if not self.alive:
                return False
            dropped = False
            while len(self._q) >= self.Q_MAX:
                self._q.popleft()
                self.dropped += 1
                dropped = True
            self._q.append(payload)
            self._cv.notify()
            return dropped

    def wakeup(self):
        """唤醒发送线程以便其退出"""
        with self._cv:
            self._cv.notify_all()

    def pending(self):
        """当前待发送帧数"""
        with self._cv:
            return len(self._q)

    def send_text(self, obj):
        """发送文本帧（JSON）"""
        self._send(OP_TEXT, json.dumps(obj, ensure_ascii=False).encode('utf-8'))

    def send_binary(self, payload):
        """发送二进制帧（同步，用于握手/小数据）"""
        self._send(OP_BIN, payload)

    def ping(self):
        """发协议级 ping：浏览器/观看端的 WS 栈会自动回 pong，不需要前端 JS 参与"""
        return self._send(OP_PING, b'')

    def close(self):
        """关闭连接"""
        with self._send_lock:
            if not self.alive:
                return
            self.alive = False
            try:
                self._sock.sendall(_encode_frame(OP_CLOSE, b''))
            except Exception:
                pass
        self.wakeup()
        try:
            self._sock.shutdown(2)
        except Exception:
            pass

    def close_hard(self):
        """回收半开连接专用：不发 CLOSE 帧、不等发送锁，避免卡住的 sendall 把回收线程一起拖死"""
        self.alive = False
        self.wakeup()
        try:
            self._sock.shutdown(2)
        except Exception:
            pass

    def _send(self, opcode, payload):
        """加锁写出一帧"""
        with self._send_lock:
            if not self.alive:
                return False
            try:
                self._sock.sendall(_encode_frame(opcode, payload))
                return True
            except Exception:
                self.alive = False
                return False

    def read(self):
        """读取一条完整消息，返回 (kind, data)；kind 为 text/bin/close/ping/pong"""
        while True:
            head = _recv_exact(self._sock, 2)
            if head is None:
                return None
            # 只要收到任何帧（含浏览器自动回的 pong）就说明链路还活着
            self.last_rx = time.time()
            b1, b2 = head[0], head[1]
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                ext = _recv_exact(self._sock, 2)
                if ext is None:
                    return None
                length = struct.unpack('>H', ext)[0]
            elif length == 127:
                ext = _recv_exact(self._sock, 8)
                if ext is None:
                    return None
                length = struct.unpack('>Q', ext)[0]
            mask = None
            if masked:
                mask = _recv_exact(self._sock, 4)
                if mask is None:
                    return None
            payload = _recv_exact(self._sock, length) if length else b''
            if payload is None:
                return None
            if mask:
                payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
            if opcode == OP_CLOSE:
                return ('close', b'')
            if opcode == OP_PING:
                self._send(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CONT:
                self._frag_buf.extend(payload)
                if fin and self._frag_op is not None:
                    kind = 'text' if self._frag_op == OP_TEXT else 'bin'
                    data = bytes(self._frag_buf)
                    self._frag_op = None
                    self._frag_buf = bytearray()
                    return (kind, data)
                continue
            if not fin:
                self._frag_op = opcode
                self._frag_buf = bytearray(payload)
                continue
            return ('text' if opcode == OP_TEXT else 'bin', payload)


class WsHub:
    """手机/观看端复用同一 WS 端点：手机上行音视频，观看端下行视频"""

    def __init__(self, on_audio=None, gop_max=16, log=None, on_drop=None,
                 ping_idle=PING_IDLE_SECS, pong_timeout=PONG_TIMEOUT_SECS,
                 keep_interval=KEEP_INTERVAL_SECS):
        self._lock = threading.Lock()
        self._conns = set()
        self._viewers = set()
        self._phones = set()
        self._vcfg = None
        self._last_reqkey = 0.0
        self._gop_max = int(gop_max)   # 兼容旧参数（已不再重放积压）
        self._on_audio = on_audio
        self._on_drop = on_drop
        self._log = log
        self._ping_idle = float(ping_idle)
        self._pong_timeout = float(pong_timeout)
        self._keep_interval = max(1.0, float(keep_interval))
        self._keeper = None
        self._keeper_lock = threading.Lock()

    # ---------- 心跳：回收半开连接 ----------
    def _ensure_keeper(self):
        """惰性启动心跳线程（有连接才需要）"""
        if self._keeper is not None:
            return
        with self._keeper_lock:
            if self._keeper is not None:
                return
            self._keeper = threading.Thread(target=self._keep_loop, daemon=True, name='ws-keep')
            self._keeper.start()

    def _keep_loop(self):
        while True:
            time.sleep(self._keep_interval)
            try:
                self.check_keepalive()
            except Exception:
                pass

    def check_keepalive(self, now=None):
        """空闲连接发 ping；超过超时时间一帧都没收到的判为半开连接，直接关掉触发回收

        手机被系统杀掉/息屏不会发 FIN，读线程会永久卡在 recv 里：
        连接和线程只增不减，最后表现成"越用越怪，只能重启服务"。
        """
        now = time.time() if now is None else float(now)
        with self._lock:
            conns = list(self._conns)
        for c in conns:
            if not c.alive:
                continue
            idle = now - (c.last_rx or now)
            if idle > self._pong_timeout:
                if self._log:
                    try:
                        self._log('[ws] 回收半开连接 role=%s 空闲 %.0fs' % (c.role or '-', idle))
                    except Exception:
                        pass
                try:
                    c.close_hard()
                except Exception:
                    pass
                continue
            if idle > self._ping_idle and (now - (c.last_ping or 0.0)) > self._ping_idle:
                c.last_ping = now
                try:
                    c.ping()
                except Exception:
                    pass

    def serve(self, sock, headers):
        """完成握手并进入读写循环（在请求线程内阻塞）"""
        key = headers.get('Sec-WebSocket-Key')
        lines = [
            'HTTP/1.1 101 Switching Protocols',
            'Upgrade: websocket',
            'Connection: Upgrade',
            'Sec-WebSocket-Accept: ' + compute_accept(key),
            '',
            '',
        ]
        try:
            sock.sendall('\r\n'.join(lines).encode('ascii'))
        except Exception:
            return
        conn = WsConn(sock)
        conn.start_sender()
        with self._lock:
            self._conns.add(conn)
        self._ensure_keeper()
        try:
            self._loop(conn)
        finally:
            self._drop(conn)

    def _loop(self, conn):
        """读取消息并分派"""
        while conn.alive:
            msg = conn.read()
            if msg is None:
                return
            kind, data = msg
            if kind == 'close':
                return
            if kind == 'text':
                self._on_text(conn, data)
            elif kind == 'bin':
                self._on_binary(conn, data)

    def _on_text(self, conn, data):
        """处理文本控制消息"""
        try:
            obj = json.loads(data.decode('utf-8'))
        except Exception:
            return
        t = obj.get('t')
        role = obj.get('role')
        if t == 'hello':
            conn.role = role
            if role == 'viewer':
                with self._lock:
                    self._viewers.add(conn)
                    vcfg = self._vcfg
                conn.send_text({'t': 'hello', 'role': 'hub'})
                if vcfg:
                    conn.send_text(dict(vcfg, t='vcfg'))
                # 不再重放 GOP 积压（最多 10 秒的旧画面 = 延迟源头），改为要一个新关键帧
                self.request_keyframe(force=True)
            elif role == 'phone':
                with self._lock:
                    self._phones.add(conn)
                conn.send_text({'t': 'hello', 'role': 'hub'})
        elif t == 'vcfg':
            cfg = {'t': 'vcfg', 'codec': obj.get('codec'), 'w': obj.get('w'),
                   'h': obj.get('h'), 'fps': obj.get('fps')}
            with self._lock:
                self._vcfg = cfg
                viewers = list(self._viewers)
            for v in viewers:
                v.send_text(dict(cfg))
        elif t == 'vstop':
            with self._lock:
                self._vcfg = None
                viewers = list(self._viewers)
            for v in viewers:
                v.send_text({'t': 'vstop'})
        elif t == 'acfg':
            conn.audio_rate = int(obj.get('rate') or 48000)
            conn.audio_ch = int(obj.get('ch') or 1)
        elif t == 'audio':
            conn.audio_on = bool(int(obj.get('on', 1)))
        elif t == 'user':
            conn.username = str(obj.get('name') or '')[:20]
        elif t == 'reqkey':
            self.request_keyframe()

    def _on_binary(self, conn, data):
        """处理二进制媒体帧（上行线程只做入队，绝不因慢 viewer 阻塞）"""
        if not data:
            return
        sub = data[0]
        if sub == SUB_VIDEO:
            if len(data) < 10:
                return
            flags = data[1]
            ts = struct.unpack('>Q', data[2:10])[0]
            body = data[10:]
            if not body:
                return
            frame = bytes([flags]) + struct.pack('>Q', ts) + body
            with self._lock:
                viewers = list(self._viewers)
            overflow = False
            for v in viewers:
                if v.enqueue_bin(frame):
                    overflow = True
            if overflow:
                # 丢过帧 → viewer 的解码链断了，补一个关键帧（限流）
                self.request_keyframe()
        elif sub == SUB_AUDIO:
            if len(data) > 1:
                pcm = data[1:]
                if self._on_audio:
                    self._on_audio(conn.audio_rate, conn.audio_ch, pcm, conn.username)
                self._broadcast_audio(conn.audio_rate, pcm)

    def _broadcast_audio(self, rate, pcm):
        """把手机上行音频旁路给观看端：/cam 在显示画面时也能放出手机采到的声音"""
        if not pcm:
            return
        try:
            frame = bytes([SUB_AUDIO_MON]) + struct.pack('>I', int(rate or 16000)) + pcm
        except Exception:
            return
        with self._lock:
            viewers = [v for v in self._viewers if v.audio_on]
        for v in viewers:
            v.enqueue_bin(frame)

    def request_keyframe(self, force=False):
        """请求手机端产生关键帧（默认 0.5s 内只发一次，避免抖动时风暴）"""
        now = time.time()
        if not force and (now - self._last_reqkey) < 0.5:
            return
        self._last_reqkey = now
        with self._lock:
            phones = list(self._phones)
        for p in phones:
            p.send_text({'t': 'reqkey'})

    def _drop(self, conn):
        """移除断开的连接（只在真正移除时通知上层一次）"""
        conn.alive = False
        conn.wakeup()
        removed = False
        with self._lock:
            if conn in self._conns:
                self._conns.discard(conn)
                removed = True
            self._viewers.discard(conn)
            self._phones.discard(conn)
        if removed and self._on_drop:
            try:
                self._on_drop(conn)
            except Exception:
                pass
