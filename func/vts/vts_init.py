# -*- coding: utf-8 -*-
# func/vts/vts_init.py
# VTS WebSocket 连接、授权与发送

import json
import threading
import websocket
from threading import Thread
from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton
from func.vts.config import VtsConfig


@singleton
class VtsInit:
    """VTS 连接核心：WebSocketApp 常驻连接 + 授权 + 通用发送"""

    # 设置控制台日志
    log = DefaultLog().getLogger()

    vtsConfig = VtsConfig()  # vts配置

    def __init__(self):
        self.ws = None
        self._connected = threading.Event()
        # 发送锁：body_sway / mouth_sync / 表情热键可能在不同线程并发 send
        self._send_lock = threading.Lock()
        if self.vtsConfig.switch == True:
            self.ws = websocket.WebSocketApp(
                f"ws://{self.vtsConfig.vtuber_websocket}",
                on_open=self.on_open,
                on_close=self.on_close,
                on_error=self.on_error,
            )
            # ws表情服务心跳包
            run_forever_thread = Thread(target=self.run_forever, daemon=True)
            run_forever_thread.start()
        else:
            self.log.info("VtubeStudio 控制已关闭")

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
        self.log.info("VtubeStudio WebSocket 连接成功")
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
                "pluginName": self.vtsConfig.vtuber_pluginName,
                "pluginDeveloper": self.vtsConfig.vtuber_pluginDeveloper,
                "authenticationToken": self.vtsConfig.vtuber_authenticationToken,
            },
        }
        try:
            self.ws.send(json.dumps(authstr))
        except Exception:
            pass

    def send(self, data):
        """发送原始指令；连接未就绪时等待，失败时返回 False"""
        if self.vtsConfig.switch == False or self.ws is None:
            return False
        if not self._connected.wait(timeout=5):
            self.log.warning("VtubeStudio 尚未连接，本次指令已跳过")
            return False
        try:
            with self._send_lock:
                self.ws.send(data)
            return True
        except Exception as e:
            self._connected.clear()
            self.log.warning(f"VtubeStudio 发送失败: {e}")
            return False

    # ============= 通用发送接口 =============
    def trigger_hotkey(self, hotkey_id: str) -> bool:
        """触发 VTS 热键（表情/动作/换装统一入口）"""
        if not hotkey_id:
            return False
        jstr = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "SomeID11",
            "messageType": "HotkeyTriggerRequest",
            "data": {"hotkeyID": str(hotkey_id)},
        }
        return self.send(json.dumps(jstr))

    def send_parameter(self, name: str, value: float, weight: float = 1.0) -> bool:
        """设置 VTS 参数值（身体摆动/嘴部开合等）。

        VTS 设置参数的标准接口是 InjectParameterDataRequest（追踪参数注入），
        而非 ParameterValueRequest（那是查询单参数值）。

        注意：VTS 要求对想控制的参数至少每秒重发一次，否则参数会被视为丢失并回退；
        body_sway / mouth_sync 的循环间隔（约 90~100ms）已满足该要求。
        """
        if not name:
            return False
        jstr = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "SomeID12",
            "messageType": "InjectParameterDataRequest",
            "data": {
                "faceFound": False,
                "mode": "set",
                "parameterValues": [
                    {"id": str(name), "value": float(value), "weight": float(weight)}
                ],
            },
        }
        return self.send(json.dumps(jstr))
