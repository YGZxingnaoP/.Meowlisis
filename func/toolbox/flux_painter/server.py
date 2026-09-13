# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/server.py
import asyncio
import json
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, quote, urlparse

import websockets

from func.log.default_log import DefaultLog


class TBFluxPainterServer:
    """画板服务：HTTP(8090) 托管 painting_board.html + 图片/审查接口，WS(8767) 按 channel 推送"""

    def __init__(self, config, html_path=None):
        self.log = DefaultLog().getLogger()
        self.config = config
        self.http_port = config.http_port
        self.ws_port = config.ws_port
        self.html_path = html_path or os.path.join(os.path.dirname(__file__), "painting_board.html")
        self._clients = {}
        self._loop = None
        self._http_thread = None
        # 项目根（server.py: 文件→flux_painter→toolbox→func→根，共4级）
        self._root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))

    # ==================== WebSocket ====================
    @staticmethod
    def _channel_of(websocket) -> str:
        channel = "live"
        try:
            req = getattr(websocket, "request", None)
            if req is not None:
                qs = getattr(req, "query_string", None)
                q = parse_qs(qs.decode("utf-8", "ignore")) if isinstance(qs, bytes) else parse_qs(qs or "")
                channel = (q.get("channel") or ["live"])[0]
        except Exception:
            channel = "live"
        return str(channel or "live")

    def _busy_gifs(self):
        """作画中展示的动图：扫 html 同级的 resource/ 目录（gif/webp/png），返回可访问 URL"""
        d = os.path.join(os.path.dirname(os.path.abspath(self.html_path)), "resource")
        urls = []
        try:
            for n in sorted(os.listdir(d)):
                if n.lower().endswith((".gif", ".webp", ".png")):
                    urls.append("/resource/" + quote(n))
        except Exception:
            self.log.warning(f"[flux_painter] resource 目录读取失败: {d}")
        return urls

    async def _websocket_handler(self, websocket):
        channel = self._channel_of(websocket)
        self._clients.setdefault(channel, set()).add(websocket)
        try:
            await websocket.send(json.dumps({
                "type": "hello",
                "canvas_sizes": self.config.canvas_sizes,
                "review": bool(self.config.review_enabled),
                "artist_sources": self.config.artist_sources,
                "busy_gifs": self._busy_gifs(),
                "painting_board": f"http://127.0.0.1:{self.http_port}/painting_board.html",
            }, ensure_ascii=False))
            await websocket.wait_closed()
        finally:
            for ch, clients in list(self._clients.items()):
                clients.discard(websocket)
                if not clients:
                    self._clients.pop(ch, None)

    async def _run_websocket_server(self):
        self._ws_server = await websockets.serve(self._websocket_handler, "127.0.0.1", self.ws_port)
        self.log.info(f"[flux_painter] 画板 WebSocket 已启动，端口 {self.ws_port}")
        await self._ws_server.wait_closed()

    def _run_event_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._run_websocket_server())

    # ==================== HTTP ====================
    def _allow_dirs(self):
        """图片可访问白名单：backup/comfy_output/temp，相对路径按项目根绝对化，
        不依赖服务启动 cwd（避免 403 误杀）"""
        allow = []
        for p in (self.config.backup_dir, self.config.comfy_output_dir,
                  getattr(self.config, "temp_dir", "")):
            if not p:
                continue
            ap = p if os.path.isabs(p) else os.path.join(self._root, p)
            rp = os.path.realpath(ap)
            if os.path.isfile(rp):
                rp = os.path.dirname(rp)
            if rp and rp not in allow:
                allow.append(rp)
        return allow

    @staticmethod
    def _inside(path, dirs):
        """path 是否在某允许目录内（Windows 大小写不敏感、防前缀伪匹配）"""
        pl = path.casefold()
        for d in dirs:
            dl = d.casefold().rstrip("/\\")
            if pl == dl or pl.startswith(dl + "\\"):
                return True
        return False

    @staticmethod
    def _dir_main_image(d):
        """目录内主图：优先 image.*，其次按名序取首个图片"""
        for name in ("image.png", "image.jpg", "image.jpeg"):
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                return cand
        try:
            for fn in sorted(os.listdir(d)):
                if fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
                    return os.path.join(d, fn)
        except Exception:
            pass
        return None

    def _paint_candidate(self, raw, allow):
        """把 /paint_img?path= 解析为真实文件：支持 相对/绝对、目录(取主图)、
        无扩展名补后缀等形态，且必须落在允许目录内；找不到返回 None"""
        if not raw:
            return None
        raw = raw.strip().strip("\"'")
        cands = []

        def _add(p):
            if not p:
                return
            try:
                p = os.path.realpath(p)
            except Exception:
                return
            if p not in cands:
                cands.append(p)

        _add(raw)
        if not os.path.isabs(raw):
            _add(os.path.join(self._root, raw))
        # 形态展开：目录→主图；无扩展名→尝试常见图像后缀
        for c in list(cands):
            if os.path.isdir(c):
                m = self._dir_main_image(c)
                if m:
                    _add(m)
            elif not os.path.isfile(c) and not os.path.splitext(c)[1]:
                for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                    _add(c + ext)
        for c in cands:
            try:
                if os.path.isfile(c) and self._inside(c, allow):
                    return c
            except Exception:
                continue
        return None

    def _make_handler(self, base_dir):
        allow = self._allow_dirs()

        class _Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=base_dir, **kwargs)

            def log_message(self, *a):
                pass

            def _send_file(self, path, ctype):
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                except Exception:
                    self.send_error(404)

            def do_GET(self):
                parsed = urlparse(self.path)
                q = parse_qs(parsed.query)
                if parsed.path == "/paint_img":
                    # 兼容两种 query：?path=<enc>（标准）与 ?<enc>（历史版本漏写 path= 前缀）
                    path = (q.get("path") or [""])[0]
                    if not path and parsed.query:
                        try:
                            import urllib.parse as _up
                            path = _up.unquote(parsed.query.split("&")[0])
                        except Exception:
                            path = ""
                    serve = outer._paint_candidate(path, allow)
                    outer.log.info(
                        f"[flux_painter] paint_img 请求: raw_query={parsed.query!r} "
                        f"path={path!r} -> {'OK ' + serve if serve else 'REJECT(403)'}")
                    if serve:
                        low = serve.lower()
                        if low.endswith(".png"):
                            ctype = "image/png"
                        elif low.endswith((".jpg", ".jpeg")):
                            ctype = "image/jpeg"
                        elif low.endswith((".webp",)):
                            ctype = "image/webp"
                        elif low.endswith(".gif"):
                            ctype = "image/gif"
                        else:
                            ctype = "application/octet-stream"
                        self._send_file(serve, ctype)
                    else:
                        self.send_error(403)
                    return
                if parsed.path == "/api/review":
                    channel = (q.get("channel") or ["live"])[0]
                    passed = (q.get("pass") or ["0"])[0] in ("1", "true")
                    try:
                        from func.toolbox.flux_painter.painting_core import TBFluxPainterCore
                        TBFluxPainterCore().review_submit(channel, passed)
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b"ok")
                    except Exception:
                        self.send_error(500)
                    return
                return super().do_GET()

        outer = self
        return _Handler

    def _start_http_server(self):
        base_dir = os.path.dirname(self.html_path)
        try:
            httpd = HTTPServer(("127.0.0.1", self.http_port), self._make_handler(base_dir))
            self._http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            self._http_thread.start()
            self.log.info(f"[flux_painter] 画板页面: http://127.0.0.1:{self.http_port}/painting_board.html")
        except Exception:
            self.log.exception(f"[flux_painter] 画板 HTTP 服务启动失败(端口 {self.http_port})")

    # ==================== 生命周期 ====================
    def start(self):
        """幂等启动画板 HTTP + WS"""
        if self._loop is not None and self._http_thread is not None and self._http_thread.is_alive():
            self.log.info("[flux_painter] 画板服务已在运行，跳过重复启动")
            return
        self._start_http_server()
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_event_loop, daemon=True).start()
        self.log.info(f"✅ Flux 绘画画板服务已启动 | HTTP: {self.http_port} | WebSocket: {self.ws_port}")

    def broadcast(self, channel, payload):
        """向指定 channel 前端推送（channel 缺省 live）"""
        channel = str(channel or "live")
        clients = (self._clients or {}).get(channel)
        if not clients or self._loop is None:
            return
        try:
            message = json.dumps(payload, ensure_ascii=False)

            async def _send_all():
                for client in list(clients):
                    try:
                        await client.send(message)
                    except Exception:
                        clients.discard(client)

            asyncio.run_coroutine_threadsafe(_send_all(), self._loop)
        except Exception:
            self.log.exception("[flux_painter] 画板广播失败")


_flux_painter_server = None


def get_flux_painter_server():
    """全局画板服务单例（api.py 启用时 start）"""
    global _flux_painter_server
    if _flux_painter_server is None:
        from func.toolbox.flux_painter.config import TBFluxPainterConfig
        _flux_painter_server = TBFluxPainterServer(TBFluxPainterConfig())
    return _flux_painter_server
