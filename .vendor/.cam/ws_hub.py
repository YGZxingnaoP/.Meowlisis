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

    def __init__(self, on_audio=None, gop_max=16, log=None):
        self._lock = threading.Lock()
        self._conns = set()
        self._viewers = set()
        self._phones = set()
        self._vcfg = None
        self._last_reqkey = 0.0
        self._gop_max = int(gop_max)   # 兼容旧参数（已不再重放积压）
        self._on_audio = on_audio
        self._log = log

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
        """移除断开的连接"""
        conn.alive = False
        conn.wakeup()
        with self._lock:
            self._conns.discard(conn)
            self._viewers.discard(conn)
            self._phones.discard(conn)
