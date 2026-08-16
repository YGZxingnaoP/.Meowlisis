import json
import threading
import websocket
from threading import Thread
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.gobal.data import VtuberData

@singleton
class VtuberInit:
    # 设置控制台日志
    log = DefaultLog().getLogger()

    vtuberData = VtuberData()  # vtuber数据

    def __init__(self):
        self.ws = None
        self._connected = threading.Event()
        if self.vtuberData.switch == True:
            self.ws = websocket.WebSocketApp(
                f"ws://{self.vtuberData.vtuber_websocket}",
                on_open=self.on_open,
                on_close=self.on_close,
                on_error=self.on_error,
            )
            # ws表情服务心跳包
            run_forever_thread = Thread(target=self.run_forever, daemon=True)
            run_forever_thread.start()
        else:
            self.log.info("VtuberStudio 控制已关闭")

    def get_ws(self):
        return self.ws

    def stop(self):
        if self.ws is not None:
            self.ws.close()

    # ============= Vtuber表情 =====================
    def run_forever(self):
        self.ws.run_forever(ping_timeout=1)

    # 注意：on_open是websocket服务的重载函数，必须有ws链接对象传入参数
    def on_open(self, ws):
        self._connected.set()
        self.log.info("VtuberStudio WebSocket 连接成功")
        self.auth()

    def on_close(self, ws, close_status_code, close_msg):
        self._connected.clear()

    def on_error(self, ws, error):
        self._connected.clear()

    # 授权Vtuber服务
    def auth(self):
        # 授权码
        authstr = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "SomeID",
            "messageType": "AuthenticationRequest",
            "data": {
                "pluginName": self.vtuberData.vtuber_pluginName,
                "pluginDeveloper": self.vtuberData.vtuber_pluginDeveloper,
                "authenticationToken": self.vtuberData.vtuber_authenticationToken,
            },
        }
        try:
            self.ws.send(json.dumps(authstr))
        except Exception:
            pass

    def send(self, data):
        """发送表情指令；连接未就绪时等待，失败时返回 False"""
        if self.vtuberData.switch == False or self.ws is None:
            return False
        if not self._connected.wait(timeout=5):
            self.log.warning("VtuberStudio 尚未连接，本次表情已跳过")
            return False
        try:
            self.ws.send(data)
            return True
        except Exception as e:
            self._connected.clear()
            self.log.warning(f"VtuberStudio 发送失败: {e}")
            return False
    # ============================================
