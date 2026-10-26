from cw.protocol import CWErrorCode, CWProtocolError


class CWScreen:
    def __init__(self, pixel_w, pixel_h, scale, orientation="portrait", safe_area=None):
        self.pixel_w = int(pixel_w)
        self.pixel_h = int(pixel_h)
        self.scale = float(scale) if scale else 1.0
        self.orientation = orientation or "portrait"
        self.safe_area = dict(safe_area or {})

    @property
    def point_size(self):
        if self.scale <= 0:
            return self.pixel_w, self.pixel_h
        return int(round(self.pixel_w / self.scale)), int(round(self.pixel_h / self.scale))

    def to_point(self, x, y):
        if self.scale <= 0:
            return int(x), int(y)
        return int(round(x / self.scale)), int(round(y / self.scale))

    def in_bounds(self, x, y):
        return 0 <= x < self.pixel_w and 0 <= y < self.pixel_h

    def check_point(self, x, y, label="坐标"):
        if not self.in_bounds(x, y):
            raise CWProtocolError(CWErrorCode.OUT_OF_RANGE,
                                  "%s(%s,%s) 超出屏幕 %sx%s" % (label, x, y, self.pixel_w, self.pixel_h))
        return True

    def check_portrait(self):
        if self.orientation != "portrait":
            raise CWProtocolError(CWErrorCode.UNSUPPORTED, "暂不支持横屏操作")
        return True

    def as_dict(self):
        return {
            "pixel": [self.pixel_w, self.pixel_h],
            "point": list(self.point_size),
            "scale": self.scale,
            "orientation": self.orientation,
            "safe_area": dict(self.safe_area),
        }

    def safe_px(self):
        area = self.safe_area or {}
        top = float(area.get("top", 0) or 0)
        bottom = float(area.get("bottom", 0) or 0)
        top_px = top * self.scale if top * self.scale <= self.pixel_h * 0.25 else top
        bottom_px = bottom * self.scale if bottom * self.scale <= self.pixel_h * 0.25 else bottom
        return int(round(top_px)), int(round(bottom_px))

    def box(self, margin=0):
        top, bottom = self.safe_px()
        pad = max(0, int(margin))
        left = pad
        right = self.pixel_w - 1 - pad
        upper = top + pad
        lower = self.pixel_h - 1 - bottom - pad
        if right <= left or lower <= upper:
            return 0, 0, self.pixel_w - 1, self.pixel_h - 1
        return left, upper, right, lower

    def clamp(self, x, y, margin=0):
        left, upper, right, lower = self.box(margin)
        return min(max(int(x), left), right), min(max(int(y), upper), lower)

    def swipe(self, direction, ratio=0.5, margin=0):
        left, upper, right, lower = self.box(margin)
        width = right - left
        height = lower - upper
        cx = (left + right) // 2
        cy = (upper + lower) // 2
        span_ratio = min(max(float(ratio or 0.5), 0.05), 0.95)
        if direction in ("up", "down"):
            span = max(1, int(height * span_ratio))
            half = span // 2
            if direction == "up":
                return [cx, max(upper, min(lower, cy + half))], [cx, max(upper, min(lower, cy - half))]
            return [cx, max(upper, min(lower, cy - half))], [cx, max(upper, min(lower, cy + half))]
        span = max(1, int(width * span_ratio))
        half = span // 2
        if direction == "left":
            return [max(left, min(right, cx + half)), cy], [max(left, min(right, cx - half)), cy]
        return [max(left, min(right, cx - half)), cy], [max(left, min(right, cx + half)), cy]

    @classmethod
    def from_device(cls, data):
        if not isinstance(data, dict):
            raise CWProtocolError(CWErrorCode.INTERNAL, "设备信息格式错误")
        screen = data.get("screen") or {}
        pixel = screen.get("pixel") or [0, 0]
        if len(pixel) != 2 or not pixel[0]:
            raise CWProtocolError(CWErrorCode.INTERNAL, "设备未上报截图尺寸")
        return cls(pixel[0], pixel[1], screen.get("scale", 1.0),
                   screen.get("orientation", "portrait"), screen.get("safe_area"))

    @classmethod
    def fallback(cls):
        return cls(1179, 2556, 3.0)
