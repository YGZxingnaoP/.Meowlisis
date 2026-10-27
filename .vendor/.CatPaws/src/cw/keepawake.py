import threading

from cw.protocol import CWProtocolError


class CWKeepAwake:
    """空闲防息屏：链路空闲超过设定秒数就轻点一下，重置系统的自动锁定计时"""

    def __init__(self, config, operator, journal=None):
        self.config = config
        self.operator = operator
        self.journal = journal
        self._thread = None
        self._stop = threading.Event()
        self._last_error = ""

    def enabled(self):
        """是否启用（keep_awake_sec <= 0 表示关闭）"""
        try:
            return int(getattr(self.config, "keep_awake_sec", 0) or 0) > 0
        except (TypeError, ValueError):
            return False

    def start(self):
        """启动后台心跳线程（线程内每 1 秒判断一次是否该点）"""
        if not self.enabled() or self._thread is not None:
            return False
        self._thread = threading.Thread(target=self._loop, name="cw-keep-awake", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """停止心跳线程"""
        self._stop.set()
        self._thread = None

    def _active(self):
        """只在链路进行中有意义：平时点屏幕可能落到键盘/按钮上"""
        session = getattr(self.operator, "session", None)
        phase = str(getattr(session, "phase", "") or "")
        return phase in ("control", "recording")

    def _loop(self):
        interval = int(getattr(self.config, "keep_awake_sec", 0) or 0)
        while not self._stop.wait(1.0):
            try:
                if not self._active():
                    continue
                if self.operator.stopping():
                    continue
                if self.operator.idle_seconds() < interval:
                    continue
                self.pulse()
            except Exception as exc:
                self._note("internal", str(exc))

    def pulse(self):
        """立刻轻点一下状态栏空白处（不进链路守卫，不会碰到输入框）"""
        device = getattr(self.operator, "device", None)
        if device is None:
            return False
        try:
            screen = self.operator.screen(refresh=False)
            x, y = self._point(screen)
            device.run_steps([{"action": "tap", "x": x, "y": y}], None)
        except CWProtocolError as exc:
            self._note(exc.code, exc.message)
            return False
        except Exception as exc:
            self._note("internal", str(exc))
            return False
        self.operator.touch()
        self._last_error = ""
        if self.journal is not None:
            self.journal.record("keep_awake", ok=True, x=x, y=y)
        return True

    def _point(self, screen):
        """点哪里：配置了坐标就用配置，否则用状态栏正中（键盘永远盖不到这里）"""
        point = list(getattr(self.config, "keep_awake_point", None) or [])
        if len(point) >= 2:
            x, y = int(point[0]), int(point[1])
        else:
            top, _ = screen.safe_px()
            x = screen.pixel_w // 2
            y = max(4, top // 2)
        x = min(max(int(x), 2), screen.pixel_w - 2)
        y = min(max(int(y), 2), screen.pixel_h - 2)
        return x, y

    def _note(self, code, message):
        """同一个错误只记一条，避免锁屏时刷屏"""
        text = "%s:%s" % (code, message)
        if text == self._last_error:
            return
        self._last_error = text
        if self.journal is not None:
            self.journal.record("keep_awake", ok=False, code=code, message=str(message)[:200])
