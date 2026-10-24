import socket
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from .config import HTTP_PORT, DEFAULT_PHONE_IP
from .wda_native_client import init_wda_client, get_wda_client
from .action_manager import list_actions, run_action, stop_action, get_running_actions
from screen import receiver                         # 屏幕接收器
from screen.coordinate_grid import generate_screen_page

# 加载 Python 环境配置（自动应用到 action_manager）
try:
    from . import env_config
except ImportError:
    pass


def get_local_ip():
    """获取本机局域网 IPv4"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def generate_status_page() -> str:
    """服务端运行状态页面（自动 3 秒刷新）"""
    wda = get_wda_client()
    is_connected = wda.is_available if wda else False
    phone_ip = wda.phone_ip if wda else DEFAULT_PHONE_IP
    
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>CatPaws 状态</title>
    <meta http-equiv="refresh" content="3">
    <style>
        body {{ font-family: sans-serif; text-align: center; margin-top: 50px; }}
        .stat {{ font-size: 24px; margin: 10px; }}
        .label {{ color: #555; }}
        .value {{ font-weight: bold; color: #2196F3; }}
    </style>
</head>
<body>
    <h2>🖥️ CatPaws WDA 模式运行中</h2>
    <div class="stat"><span class="label">📱 WDA 连接：</span><span class="value" id="wda_status">{'✅ 已连接' if is_connected else '❌ 未连接'}</span></div>
    <div class="stat"><span class="label">🎯 目标手机：</span><span class="value">{phone_ip}</span></div>
    <p style="margin-top:40px;"><a href="/">控制面板</a></p>
</body>
</html>"""


# ---- 事件循环引用（用于在 HTTP 线程中调度协程） ----
_loop = None


def set_event_loop(loop):
    """注入 asyncio 事件循环，供 HTTP 线程调度异步任务"""
    global _loop
    _loop = loop


class MultiPageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_static("index.html")
        elif self.path == "/status":
            content = generate_status_page()
            self._send_html(content)
        elif self.path == "/screen":
            self._handle_screen_page()
        elif self.path == "/api/status":
            wda = get_wda_client()
            initialized = wda is not None and wda.has_session
            connected = wda.is_available if wda else False
            phone_ip = wda.phone_ip if wda else DEFAULT_PHONE_IP
            self._send_json({
                "initialized": initialized,
                "connected": connected,
                "phone_ip": phone_ip,
            })
        elif self.path == "/api/actions":
            actions = list_actions()
            self._send_json({"type": "action_list", "actions": actions})
        elif self.path == "/api/running_actions":
            running = get_running_actions()
            self._send_json({"type": "running_action_list", "actions": running})
        elif self.path == "/api/screen":
            self._send_json({"has_screenshot": receiver.get_latest_image() is not None})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/init_sender":
            self._handle_init_sender()
        elif self.path == "/api/run_action":
            self._handle_run_action()
        elif self.path == "/api/stop_action":
            self._handle_stop_action()
        elif self.path == "/api/screen":
            self._handle_screen_upload()
        else:
            self.send_error(404)

    # ---- 屏幕截图页面 ----
    def _handle_screen_page(self):
        """生成屏幕页面，先从 WDA 拉取截图同步到 receiver"""
        wda = get_wda_client()
        if wda and wda.has_session:
            img = wda.screenshot()
            if img:
                # 同步截图到 receiver，供 coordinate_grid 显示
                import io, base64
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                png_bytes = buf.getvalue()
                receiver._latest_image = png_bytes
                receiver._width, receiver._height = img.size
                # 同步截图尺寸到坐标系统
                from screen import coord_system
                coord_system.set_screenshot_size(img.width, img.height)
                # 尝试计算 scale
                logical_w, _ = wda.get_screen_size()
                if logical_w and logical_w > 0:
                    scale = round(img.width / logical_w, 1)
                    receiver.set_scale(scale)

        content = generate_screen_page(receiver)
        self._send_html(content)

    # ---- WDA 初始化 ----
    def _handle_init_sender(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        try:
            data = json.loads(post_data)
            phone_ip = data.get("phone_ip", DEFAULT_PHONE_IP)
            port = data.get("port", 8100)

            ok = init_wda_client(phone_ip, port)
            if ok:
                w, h = get_wda_client().get_screen_size()
                self._send_json({"status": "ok", "message": f"WDA 已连接 {phone_ip}:{port}（逻辑尺寸 {w}x{h}pt）"})
            else:
                self._send_json({"status": "error", "message": f"WDA 会话创建失败，请检查 {phone_ip}:{port}"})
        except Exception as e:
            self._send_json({"error": str(e)})

    # ---- 截图上传（保留兼容） ----
    def _handle_screen_upload(self):
        self._send_json({"status": "deprecated", "message": "HTTP 模式下请使用 WDA /screenshot 接口"})

    # ---- 动作管理 ----
    def _handle_run_action(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        try:
            data = json.loads(post_data)
            name = data.get("name")
            if not name:
                self._send_json({"error": "missing name"})
                return

            wda = get_wda_client()
            if not wda or not wda.has_session:
                self._send_json({"error": "WDA 客户端未初始化，请先连接"})
                return
            
            # 检查是否已经在运行
            running = get_running_actions()
            if name in running:
                self._send_json({"error": f"脚本 {name} 已在运行中"})
                return

            if _loop:
                import asyncio
                asyncio.run_coroutine_threadsafe(run_action(name), _loop)
            self._send_json({"type": "action_started", "name": name})
        except Exception as e:
            self._send_json({"error": str(e)})

    def _handle_stop_action(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        try:
            data = json.loads(post_data)
            name = data.get("name")
            if not name:
                self._send_json({"error": "missing name"})
                return
            
            success = stop_action(name)
            if success:
                self._send_json({"status": "ok", "message": f"脚本 {name} 已停止"})
            else:
                self._send_json({"error": f"脚本 {name} 未在运行或停止失败"})
        except Exception as e:
            self._send_json({"error": str(e)})

    # ---- 静态文件 ----
    def _serve_static(self, filename: str):
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        file_path = os.path.join(static_dir, filename)
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            content_type = "text/html; charset=utf-8"
            if filename.endswith(".js"):
                content_type = "application/javascript"
            elif filename.endswith(".css"):
                content_type = "text/css"
            self.send_response(200)
            self.send_header("Content-type", content_type)
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404)

    def _send_html(self, content: str):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _send_json(self, data: dict):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format, *args):
        pass


def start_http_server():
    server = HTTPServer(("0.0.0.0", HTTP_PORT), MultiPageHandler)
    local_ip = get_local_ip()
    print(f"🌐 控制面板       http://{local_ip}:{HTTP_PORT}")
    print(f"🖥️  状态页面     http://{local_ip}:{HTTP_PORT}/status")
    print(f"📱 屏幕控制台    http://{local_ip}:{HTTP_PORT}/screen")
    server.serve_forever()


def start_http_server_background():
    t = Thread(target=start_http_server, daemon=True)
    t.start()
