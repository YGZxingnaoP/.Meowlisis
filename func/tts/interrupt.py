# func/tts/interrupt.py
# TTS 打断逻辑：支持 pipeline 状态打断 / 全局按键打断 / 关闭
import ctypes
import threading
import time

from func.log.default_log import DefaultLog


class InterruptManager:
    """根据配置监听打断信号，触发回调"""

    # 常用按键名 -> Windows 虚拟键码
    KEY_MAP = {
        "esc": 0x1B, "escape": 0x1B,
        "space": 0x20, "spacebar": 0x20,
        "enter": 0x0D, "return": 0x0D,
        "tab": 0x09, "backspace": 0x08,
        "ctrl": 0x11, "control": 0x11,
        "shift": 0x10, "alt": 0x12,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
        "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
        "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    }

    def __init__(self, config, on_interrupt, sensevoice_tts=None, is_paused=None):
        self.config = config
        self.log = DefaultLog().getLogger()
        self.on_interrupt = on_interrupt
        self.sensevoice_tts = sensevoice_tts
        self.is_paused = is_paused or (lambda: False)
        self.vk = self._parse_key(config.interrupt_key)
        self._last_speaking = False
        self._last_key_down = False
        self._thread = None

    def start(self):
        """启动打断监听后台线程"""
        if self.config.interrupt_mode == "off":
            self.log.info("TTS 打断功能已关闭")
            return
        if self.config.interrupt_mode == "keyboard" and self.vk is None:
            self.log.warning(f"无法识别的打断按键 '{self.config.interrupt_key}'，打断功能不可用")
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.log.info(f"TTS 打断监听已启动: mode={self.config.interrupt_mode}, key={self.config.interrupt_key}")

    def _loop(self):
        """轮询打断信号，暂停时重置状态"""
        interval = max(0.01, self.config.interrupt_poll_interval)
        while True:
            time.sleep(interval)
            if self.is_paused():
                self._last_speaking = False
                self._last_key_down = False
                continue
            if self.config.interrupt_mode == "keyboard":
                self._poll_keyboard()
            elif self.config.interrupt_mode == "pipeline":
                self._poll_pipeline()

    def _poll_keyboard(self):
        """检测全局按键按下（上升沿触发一次）"""
        pressed = self._is_key_down()
        if pressed and not self._last_key_down:
            self.log.info("检测到打断按键，打断 AI 语音")
            self.on_interrupt()
        self._last_key_down = pressed

    def _poll_pipeline(self):
        """检测用户说话状态（上升沿触发一次）"""
        speaking = False
        if self.sensevoice_tts is not None:
            try:
                speaking = self.sensevoice_tts.is_speaking()
            except Exception:
                speaking = False
        if speaking and not self._last_speaking:
            self.log.info("检测到用户开始说话，打断 AI 语音")
            self.on_interrupt()
        self._last_speaking = speaking

    def _is_key_down(self):
        """读取指定虚拟键的按下状态（Windows 全局按键）"""
        try:
            user32 = ctypes.windll.user32
        except Exception:
            return False
        try:
            return bool(user32.GetAsyncKeyState(self.vk) & 0x8000)
        except Exception:
            return False

    @staticmethod
    def _parse_key(key):
        """解析按键名/单字符/虚拟键码为虚拟键码"""
        if isinstance(key, int):
            return key
        k = str(key).strip().lower()
        if k in InterruptManager.KEY_MAP:
            return InterruptManager.KEY_MAP[k]
        if len(k) == 1 and k.isalnum():
            if k.isdigit():
                return 0x30 + int(k)
            return ord(k.upper())
        return None
