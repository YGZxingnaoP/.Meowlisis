import io
import threading
import time

from PIL import Image, ImageDraw, ImageFont

from cw.geometry import CWScreen
from cw.protocol import CWErrorCode, CWProtocolError, describe

CW_MOCK_APPS = [
    ("WeChat", (78, 196, 120)),
    ("Music", (232, 88, 88)),
    ("Photos", (240, 190, 70)),
    ("Settings", (120, 130, 145)),
    ("Maps", (90, 150, 235)),
    ("Notes", (250, 225, 120)),
    ("Weather", (110, 190, 240)),
    ("Clock", (60, 70, 90)),
    ("Calendar", (235, 120, 120)),
    ("Files", (130, 190, 230)),
    ("Mail", (100, 170, 240)),
    ("Safari", (90, 170, 240)),
]


class CWMockDevice:
    is_mock = True

    def __init__(self, config=None):
        self.config = config
        self.pixel_w = 1179
        self.pixel_h = 2556
        self.scale = 3.0
        self._screen = CWScreen(self.pixel_w, self.pixel_h, self.scale)
        self._session = True
        self._lock = threading.Lock()
        self._stopped = False
        self._history = []
        self._frame = 0

    def ping(self):
        return {"app": "CWMockDevice", "version": "1.0.0", "session": self._session}

    def device_info(self, refresh=False):
        return {
            "screen": self._screen.as_dict(),
            "system": {"model": "iPhone15,2", "ios": "17.4.1", "name": "Mock"},
            "capabilities": ["tap", "long_press", "swipe", "pinch", "type_text", "paste_text",
                             "press_key", "launch_app", "activate_app", "terminate_app",
                             "screenshot", "ocr"],
            "session": self._session,
        }

    def screen(self, refresh=False):
        return self._screen

    def capabilities(self):
        return self.device_info()["capabilities"]

    def ensure_session(self):
        self._session = True
        return True

    def drop_session(self):
        self._session = False
        return True

    def run_steps(self, steps, delay_ms=None):
        with self._lock:
            if self._stopped:
                self._stopped = False
                return {"executed": 0, "results": [], "cancelled": True}
        results = []
        started = time.time()
        for index, step in enumerate(steps):
            name = step.get("action")
            for field in ("x", "y"):
                if field in step:
                    value = step[field]
                    width = self.pixel_w if field == "x" else self.pixel_h
                    if not 0 <= value < width:
                        raise CWProtocolError(CWErrorCode.OUT_OF_RANGE,
                                              "%s(%s) 超出屏幕" % (field, value))
            if name == "swipe":
                for point in (step.get("from"), step.get("to")):
                    if point and not self._screen.in_bounds(point[0], point[1]):
                        raise CWProtocolError(CWErrorCode.OUT_OF_RANGE, "滑动坐标越界")
            if name in ("launch_app", "activate_app", "terminate_app"):
                if not step.get("bundle_id"):
                    raise CWProtocolError(CWErrorCode.BAD_REQUEST, "缺少 bundle_id")
            results.append({"index": index, "action": name, "ok": True,
                            "code": CWErrorCode.OK, "elapsed_ms": 20})
            with self._lock:
                self._history.append({"at": time.time(), "step": step})
                self._history = self._history[-400:]
                if self._stopped:
                    self._stopped = False
                    return {"executed": index + 1, "results": results, "cancelled": True}
        elapsed = int((time.time() - started) * 1000)
        return {"executed": len(results), "results": results, "elapsed_ms": elapsed}

    def stop(self):
        with self._lock:
            self._stopped = True
        return {"cancelled": True, "remaining_steps": 0}

    def _font(self, size):
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    def _render(self, scale_edge=None):
        width, height = self.pixel_w, self.pixel_h
        image = Image.new("RGB", (width, height), (28, 32, 42))
        draw = ImageDraw.Draw(image)
        for y in range(height):
            ratio = y / float(height)
            draw.line([(0, y), (width, y)],
                      fill=(int(30 + 20 * ratio), int(34 + 24 * ratio), int(48 + 30 * ratio)))
        font = self._font(30)
        draw.text((60, 90), "12:00", font=self._font(46), fill=(240, 242, 246))
        draw.text((60, 170), "CatPaws Mock Screen", font=font, fill=(200, 210, 225))
        label_boxes = []
        columns, rows = 4, 3
        pad_x, pad_y = 90, 380
        cell_w = (width - pad_x * 2) // columns
        cell_h = 300
        for index, (label, color) in enumerate(CW_MOCK_APPS):
            column = index % columns
            row = index // columns
            if row >= rows:
                break
            x0 = pad_x + column * cell_w + 20
            y0 = pad_y + row * cell_h
            size = 150
            draw.rounded_rectangle([x0, y0, x0 + size, y0 + size], radius=34, fill=color)
            draw.text((x0 + size + 22, y0 + 58), label, font=font, fill=(235, 238, 244))
            label_boxes.append((label, [x0 + size + 22, y0 + 58, 220, 40]))
        dock_y = height - 300
        draw.rounded_rectangle([70, dock_y - 20, width - 70, dock_y + 190], radius=60, fill=(44, 50, 64))
        for index, (label, color) in enumerate(CW_MOCK_APPS[:4]):
            x0 = 130 + index * 250
            draw.rounded_rectangle([x0, dock_y, x0 + 140, dock_y + 140], radius=30, fill=color)
        text = "Home"
        draw.text((width // 2 - 40, dock_y + 40), text, font=font, fill=(255, 255, 255))
        label_boxes.append((text, [width // 2 - 40, dock_y + 40, 110, 40]))
        if scale_edge and width > scale_edge:
            ratio = scale_edge / float(width)
            image = image.resize((int(width * ratio), int(height * ratio)), Image.LANCZOS)
        return image, label_boxes

    def screenshot(self, max_edge=None, fmt="png", quality=None):
        image, _ = self._render(max_edge)
        buffer = io.BytesIO()
        if fmt == "jpeg":
            image.save(buffer, format="JPEG", quality=int(quality or 85))
        else:
            image.save(buffer, format="PNG")
        self._frame += 1
        return buffer.getvalue()

    def ocr(self, region=None):
        _, boxes = self._render(None)
        texts = []
        for label, box in boxes:
            texts.append({"text": label, "box": box, "confidence": 0.99})
        return {"image_size": [self.pixel_w, self.pixel_h], "texts": texts}

    def paste(self, text, submit=False):
        with self._lock:
            self._history.append({"at": time.time(), "step": {"action": "paste_text", "text": text}})
        return {"pasted": True, "submitted": bool(submit)}

    def source(self):
        return {"elements": [{"label": label, "frame": box} for label, box in self._render(None)[1]]}

    def history(self, limit=50):
        with self._lock:
            return list(self._history[-limit:])

    def close(self):
        return None
