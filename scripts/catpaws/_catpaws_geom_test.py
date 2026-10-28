"""catpaws 几何自检：安全区夹取、swipe 归一化、短滑动拒绝、限速、图像尺寸。

用法：runtime\\311\\python.exe scripts\\_catpaws_geom_test.py
不需要手机，也不需要起服务。
"""
import io
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, ".vendor", ".CatPaws", "src"))

from cw.geometry import CWScreen
from cw.protocol import CWProtocolError, describe, distance, normalize_step
from cw.ops import CWOperator, image_size
from cw.guard import CWGuard

screen = CWScreen(1284, 2778, 3.0, safe_area={"top": 47, "bottom": 34})
print("safe_px", screen.safe_px())
print("box(60)", screen.box(60))
print("clamp", screen.clamp(10, 2777, 8))
print("swipe up", screen.swipe("up", 0.5, 60))
print("swipe down", screen.swipe("down", 0.5, 60))


class Device:
    def screen(self, refresh=False):
        return screen


class Config:
    swipe_min_px = 90
    swipe_margin_px = 60
    tap_margin_px = 8
    swipe_speed_px_ms = 1.2


class Session:
    IDLE = "idle"


class Journal:
    def record(self, *args, **kwargs):
        return {}


cfg = types.SimpleNamespace(max_actions_per_second=5, max_steps_per_session=200,
                            sequence_steps=10, session_timeout_sec=900)
op = CWOperator(Config(), Device(), CWGuard(cfg), Journal(), Session())
steps = [
    normalize_step({"action": "swipe", "direction": "up", "ratio": 0.5}),
    normalize_step({"action": "swipe", "from": [100, 2600], "to": [100, 300]}),
    normalize_step({"action": "tap", "x": 5, "y": 2770}),
]
for step in op.prepare(steps):
    span = distance(step["from"], step["to"]) if step.get("from") else ""
    print(describe(step), "dur=%s" % step.get("duration_ms"),
          "from=%s" % step.get("from"), "to=%s" % step.get("to"),
          "x=%s y=%s" % (step.get("x"), step.get("y")), "span=%s" % span)

for bad in [{"action": "swipe", "from": [500, 1000], "to": [510, 1030]},
            {"action": "swipe"},
            {"action": "swipe", "direction": "diagonal"}]:
    try:
        op.prepare([normalize_step(bad)])
        print("NOT REJECTED", bad)
    except CWProtocolError as exc:
        print("rejected:", exc.code, exc.message)

guard = CWGuard(cfg)
for index in range(6):
    try:
        guard.check_rate()
        print("rate", index + 1, "ok")
    except Exception as exc:
        print("rate", index + 1, "rejected:", exc)

from PIL import Image
buf = io.BytesIO()
Image.new("RGB", (591, 1280)).save(buf, format="PNG")
print("image_size", image_size(buf.getvalue()))
