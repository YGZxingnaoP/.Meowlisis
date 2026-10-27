import base64
import io
import json
import sys


class CWScriptCancelled(Exception):
    pass


class CWScriptError(Exception):
    pass


def _send(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read():
    line = sys.stdin.readline()
    if not line:
        raise CWScriptCancelled("parent closed")
    return json.loads(line)


def _request(payload):
    _send(payload)
    reply = _read()
    if not reply.get("ok"):
        code = reply.get("code") or ""
        if code == "E_CANCELLED":
            raise CWScriptCancelled(reply.get("message") or "cancelled")
        raise CWScriptError(reply.get("message") or code or "failed")
    return reply


def emit(step=None, steps=None, delay_ms=None):
    if steps is not None:
        return _request({"op": "emit", "steps": list(steps), "delay_ms": delay_ms})
    if step is None:
        raise CWScriptError("emit 需要 step 或 steps")
    return _request({"op": "emit", "step": step})


def screen():
    """屏幕信息：pixel 像素尺寸、point 点尺寸、scale、safe_area"""
    return _request({"op": "screen"}).get("screen") or {}


def tap(x, y):
    return emit({"action": "tap", "x": int(x), "y": int(y)})


def long_press(x, y, duration_ms):
    return emit({"action": "long_press", "x": int(x), "y": int(y),
                 "duration_ms": int(duration_ms)})


def swipe(from_xy, to_xy, duration_ms=300):
    return emit({"action": "swipe", "from": list(from_xy), "to": list(to_xy),
                 "duration_ms": int(duration_ms)})


def swipe_dir(direction, ratio=0.5, duration_ms=None):
    """按方向滑（up/down/left/right + 比例），起止点与时长交给 PC 算"""
    step = {"action": "swipe", "direction": str(direction), "ratio": float(ratio)}
    if duration_ms:
        step["duration_ms"] = int(duration_ms)
    return emit(step)


def wait(duration_ms):
    return emit({"action": "wait", "duration_ms": int(duration_ms)})


def press_key(key="home"):
    return emit({"action": "press_key", "key": str(key)})


def home():
    return press_key("home")


def type_text(text):
    """只支持 ASCII；中文用 paste_text"""
    return emit({"action": "type_text", "text": str(text)})


def paste_text(text):
    return emit({"action": "paste_text", "text": str(text)})


def launch_app(bundle_id):
    return emit({"action": "launch_app", "bundle_id": str(bundle_id)})


def activate_app(bundle_id):
    return emit({"action": "activate_app", "bundle_id": str(bundle_id)})



def observe(mode="ocr", region=None):
    return _request({"op": "observe", "mode": mode, "region": region})


def observe_texts(region=None):
    reply = observe("ocr", region)
    return reply.get("texts") or []


def observe_image(region=None):
    reply = observe("image", region)
    raw = reply.get("png_b64") or ""
    return base64.b64decode(raw)


def ocr_find(target, region=None, exact=False):
    """在 OCR 结果里找一段文字，命中返回 (中心x, 中心y, box)，找不到返回 None"""
    wanted = str(target or "").strip()
    if not wanted:
        return None
    for item in observe_texts(region):
        label = str(item.get("text") or "")
        hit = (label == wanted) if exact else (wanted in label)
        if not hit:
            continue
        box = item.get("box") or [0, 0, 0, 0]
        try:
            return (int(box[0] + box[2] / 2), int(box[1] + box[3] / 2), list(box))
        except (TypeError, IndexError):
            continue
    return None


def tap_text(target, region=None, exact=False):
    """按文字点击：OCR 找到就点它的中心"""
    found = ocr_find(target, region, exact)
    if not found:
        raise CWScriptError("屏幕上没找到「%s」" % target)
    tap(found[0], found[1])
    return found


def ask(question, options=None):
    reply = _request({"op": "ask", "question": str(question), "options": list(options or [])})
    return reply.get("answer") or ""


def params():
    return _request({"op": "params"}).get("params") or {}


def log(text):
    _send({"op": "log", "text": str(text)})


def done(ok=True, text=""):
    _send({"op": "done", "ok": bool(ok), "text": str(text)})


def should_stop():
    return bool(_request({"op": "probe"}).get("stop"))


def image_from_bytes(raw):
    from PIL import Image
    image = Image.open(io.BytesIO(raw))
    image.load()
    return image
