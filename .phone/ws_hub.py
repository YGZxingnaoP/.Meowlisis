import base64
import hashlib
import json
import struct
import threading

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
    """单条 WebSocket 连接：分帧收发 + 独立发送锁"""

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

    def send_text(self, obj):
        """发送文本帧（JSON）"""
        self._send(OP_TEXT, json.dumps(obj, ensure_ascii=False).encode('utf-8'))

    def send_binary(self, payload):
        """发送二进制帧"""
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

    def __init__(self, on_audio=None, gop_max=300, log=None):
        self._lock = threading.Lock()
        self._conns = set()
        self._viewers = set()
        self._phones = set()
        self._vcfg = None
        self._gop = []
        self._gop_max = int(gop_max)
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
                    gop = list(self._gop)
                conn.send_text({'t': 'hello', 'role': 'hub'})
                if vcfg:
                    conn.send_text(dict(vcfg, t='vcfg'))
                for item in gop:
                    conn.send_binary(item)
                self.request_keyframe()
            elif role == 'phone':
                with self._lock:
                    self._phones.add(conn)
                conn.send_text({'t': 'hello', 'role': 'hub'})
        elif t == 'vcfg':
            cfg = {'t': 'vcfg', 'codec': obj.get('codec'), 'w': obj.get('w'),
                   'h': obj.get('h'), 'fps': obj.get('fps')}
            with self._lock:
                self._vcfg = cfg
                self._gop = []
                viewers = list(self._viewers)
            for v in viewers:
                v.send_text(dict(cfg))
        elif t == 'vstop':
            with self._lock:
                self._vcfg = None
                self._gop = []
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
        """处理二进制媒体帧"""
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
                if flags & 0x01:
                    self._gop = [frame]
                else:
                    self._gop.append(frame)
                    if len(self._gop) > self._gop_max:
                        self._gop = self._gop[-self._gop_max:]
                viewers = list(self._viewers)
            for v in viewers:
                v.send_binary(frame)
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
            try:
                v.send_binary(frame)
            except Exception:
                pass

    def request_keyframe(self):
        """请求手机端产生关键帧"""
        with self._lock:
            phones = list(self._phones)
        for p in phones:
            p.send_text({'t': 'reqkey'})

    def _drop(self, conn):
        """移除断开的连接"""
        conn.alive = False
        with self._lock:
            self._conns.discard(conn)
            self._viewers.discard(conn)
            self._phones.discard(conn)
