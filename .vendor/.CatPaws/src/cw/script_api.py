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


def tap(x, y):
    return emit({"action": "tap", "x": int(x), "y": int(y)})


def long_press(x, y, duration_ms):
    return emit({"action": "long_press", "x": int(x), "y": int(y),
                 "duration_ms": int(duration_ms)})


def swipe(from_xy, to_xy, duration_ms=300):
    return emit({"action": "swipe", "from": list(from_xy), "to": list(to_xy),
                 "duration_ms": int(duration_ms)})


def wait(duration_ms):
    return emit({"action": "wait", "duration_ms": int(duration_ms)})


def observe(mode="ocr", region=None):
    return _request({"op": "observe", "mode": mode, "region": region})


def observe_texts(region=None):
    reply = observe("ocr", region)
    return reply.get("texts") or []


def observe_image(region=None):
    reply = observe("image", region)
    raw = reply.get("png_b64") or ""
    return base64.b64decode(raw)


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
