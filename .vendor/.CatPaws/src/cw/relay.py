import json
import threading
import time
from urllib.parse import parse_qs, urlparse

from websockets.sync.server import serve


class CWRelay:
    def __init__(self, config, journal):
        self.config = config
        self.journal = journal
        self.on_stop = None
        self._lock = threading.RLock()
        self._device = None
        self._viewers = set()
        self._vcfg = None
        self._server = None
        self._thread = None
        self._frames = 0
        self._frames_window = []
        self._last_frame_at = 0.0
        self._streaming = False
        self._src = ""

    def start(self):
        try:
            self._server = serve(self._handle, self.config.relay_host, self.config.relay_port,
                                 max_size=16 * 1024 * 1024, ping_interval=20, ping_timeout=60)
        except Exception as exc:
            raise RuntimeError("中继端口 %s 启动失败：%s" % (self.config.relay_port, exc))
        self._thread = threading.Thread(target=self._serve, name="cw-relay", daemon=True)
        self._thread.start()
        self.journal.record("relay", action="start", port=self.config.relay_port)

    def _serve(self):
        try:
            self._server.serve_forever()
        except Exception:
            pass

    def stop(self):
        try:
            if self._server is not None:
                self._server.shutdown()
        except Exception:
            pass
        self._streaming = False

    def _handle(self, ws):
        role = ""
        path = ""
        try:
            request = getattr(ws, "request", None)
            if request is not None:
                path = getattr(request, "path", "") or ""
            params = parse_qs(urlparse(path).query)
            token = (params.get("token") or [""])[0]
            role = (params.get("role") or [""])[0]
            if self.config.token and token != self.config.token:
                self._send(ws, {"t": "error", "code": "E_UNAUTHORIZED"})
                ws.close()
                return
            while True:
                try:
                    data = ws.recv()
                except Exception:
                    break
                if isinstance(data, (bytes, bytearray)):
                    self._on_bin(ws, data)
                else:
                    role = self._on_text(ws, role, data)
        except Exception:
            pass
        finally:
            self._drop(ws)

    def _send(self, ws, payload):
        try:
            ws.send(json.dumps(payload, ensure_ascii=False))
            return True
        except Exception:
            return False

    def _on_text(self, ws, role, data):
        try:
            obj = json.loads(data)
        except Exception:
            return role
        kind = obj.get("t")
        if kind == "hello":
            role = str(obj.get("role") or role or "")
            if role == "device":
                with self._lock:
                    self._device = ws
                    self._src = str(obj.get("src") or "screen")
                self._send(ws, {"t": "hello", "role": "hub"})
                self._apply_stream(ws)
                self.journal.record("relay", action="device_online", src=self._src,
                                    app=obj.get("app", ""))
            elif role == "viewer":
                with self._lock:
                    self._viewers.add(ws)
                    vcfg = self._vcfg
                self._send(ws, {"t": "hello", "role": "hub"})
                if vcfg:
                    self._send(ws, dict(vcfg, t="vcfg"))
                self.request_key()
            return role
        if kind == "vcfg":
            cfg = {"codec": obj.get("codec"), "w": obj.get("w"), "h": obj.get("h"),
                   "fps": obj.get("fps")}
            with self._lock:
                self._vcfg = cfg
                viewers = list(self._viewers)
            for viewer in viewers:
                self._send(viewer, dict(cfg, t="vcfg"))
            return role
        if kind == "vstop":
            with self._lock:
                self._vcfg = None
                viewers = list(self._viewers)
                self._streaming = False
            for viewer in viewers:
                self._send(viewer, {"t": "vstop"})
            return role
        if kind == "stats":
            with self._lock:
                self._stats = obj
            return role
        if kind == "reqkey":
            self.request_key()
            return role
        if kind == "stop_request":
            self.journal.record("stop", reason="app_button")
            if callable(self.on_stop):
                try:
                    self.on_stop()
                except Exception:
                    pass
            return role
        return role

    def _on_bin(self, ws, data):
        if len(data) < 10:
            return
        body = bytes(data)
        if body[0] == 0x01:
            frame = body[1:]
        else:
            frame = body
        with self._lock:
            viewers = list(self._viewers)
            if not viewers:
                return
        broken = []
        for viewer in viewers:
            try:
                viewer.send(frame)
            except Exception:
                broken.append(viewer)
        if broken:
            with self._lock:
                for viewer in broken:
                    self._viewers.discard(viewer)
        with self._lock:
            self._frames += 1
            now = time.time()
            self._frames_window.append(now)
            while self._frames_window and now - self._frames_window[0] > 1.0:
                self._frames_window.pop(0)
            self._last_frame_at = now

    def _drop(self, ws):
        with self._lock:
            if self._device is ws:
                self._device = None
                self._streaming = False
                self._vcfg = None
            self._viewers.discard(ws)

    def _apply_stream(self, ws):
        if self._streaming:
            self._send(ws, {"t": "start", "fps": self.config.stream_fps,
                            "max_edge": self.config.stream_max_edge,
                            "bitrate": self.config.stream_bitrate})

    def start_stream(self):
        with self._lock:
            device = self._device
            self._streaming = True
        if device is None:
            return False
        return self._send(device, {"t": "start", "fps": self.config.stream_fps,
                                   "max_edge": self.config.stream_max_edge,
                                   "bitrate": self.config.stream_bitrate})

    def stop_stream(self):
        with self._lock:
            device = self._device
            self._streaming = False
        if device is None:
            return False
        return self._send(device, {"t": "stop"})

    def request_key(self):
        with self._lock:
            device = self._device
        if device is None:
            return False
        return self._send(device, {"t": "reqkey"})

    def broadcast_op(self, entry):
        payload = {"t": "op", "entry": entry}
        with self._lock:
            targets = list(self._viewers)
            if self._device is not None:
                targets.append(self._device)
        for target in targets:
            self._send(target, payload)

    def status(self):
        with self._lock:
            fps = len(self._frames_window)
            return {
                "device_online": self._device is not None,
                "viewers": len(self._viewers),
                "streaming": self._streaming,
                "fps": fps,
                "vcfg": self._vcfg,
                "frames": self._frames,
                "src": self._src,
                "port": self.config.relay_port,
                "token": self.config.token,
            }
