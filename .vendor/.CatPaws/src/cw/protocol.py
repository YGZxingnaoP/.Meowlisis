import math

MIN_DELAY_MS = 90
MAX_DELAY_MS = 2000
MAX_STEPS_PER_BATCH = 64
MAX_SEQUENCE_STEPS = 20


class CWErrorCode:
    OK = "OK"
    BAD_REQUEST = "E_BAD_REQUEST"
    UNAUTHORIZED = "E_UNAUTHORIZED"
    UNSUPPORTED = "E_UNSUPPORTED"
    OUT_OF_RANGE = "E_OUT_OF_RANGE"
    DEVICE_LOCKED = "E_DEVICE_LOCKED"
    SESSION_LOST = "E_SESSION_LOST"
    TIMEOUT = "E_TIMEOUT"
    BUSY = "E_BUSY"
    CANCELLED = "E_CANCELLED"
    NOT_FOUND = "E_NOT_FOUND"
    INTERNAL = "E_INTERNAL"
    GUARD = "E_GUARD"
    LOCKED_ACTION = "E_ACTION_LOCKED"
    UNAVAILABLE = "E_UNAVAILABLE"
    QUESTION_DENIED = "E_QUESTION_DENIED"


class CWProtocolError(Exception):
    def __init__(self, code, message="", data=None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.data = data or {}


class CWActionSpec:
    def __init__(self, name, point_fields=(), int_fields=None, num_fields=None, str_fields=(), required=()):
        self.name = name
        self.point_fields = tuple(point_fields)
        self.int_fields = dict(int_fields or {})
        self.num_fields = dict(num_fields or {})
        self.str_fields = tuple(str_fields)
        self.required = tuple(required)


def _specs():
    specs = {}
    specs["tap"] = CWActionSpec("tap", point_fields=("x", "y"),
                                int_fields={"count": (1, 3, 1)}, required=("x", "y"))
    specs["long_press"] = CWActionSpec("long_press", point_fields=("x", "y"),
                                       int_fields={"duration_ms": (200, 5000, 800)},
                                       required=("x", "y"))
    specs["swipe"] = CWActionSpec("swipe")
    specs["pinch"] = CWActionSpec("pinch", point_fields=("x", "y"),
                                  num_fields={"scale": (0.2, 5.0, 2.0)},
                                  int_fields={"duration_ms": (100, 2000, 400)},
                                  required=("x", "y"))
    specs["type_text"] = CWActionSpec("type_text", str_fields=("text",), required=("text",))
    specs["paste_text"] = CWActionSpec("paste_text", str_fields=("text",), required=("text",))
    specs["press_key"] = CWActionSpec("press_key", str_fields=("key",), required=("key",))
    specs["launch_app"] = CWActionSpec("launch_app", str_fields=("bundle_id",), required=("bundle_id",))
    specs["activate_app"] = CWActionSpec("activate_app", str_fields=("bundle_id",), required=("bundle_id",))
    specs["terminate_app"] = CWActionSpec("terminate_app", str_fields=("bundle_id",), required=("bundle_id",))
    specs["wait"] = CWActionSpec("wait", int_fields={"duration_ms": (0, 10000, 300)},
                                 required=("duration_ms",))
    return specs


SPECS = _specs()
PRESS_KEYS = ("home", "volume_up", "volume_down", "delete", "return")
SWIPE_DIRECTIONS = ("up", "down", "left", "right")
SWIPE_EDGES = ("left", "right", "top", "bottom")


def _as_int(value, lower, upper, default, field):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "%s 必须是整数" % field)
    number = int(round(value))
    if number < lower or number > upper:
        raise CWProtocolError(CWErrorCode.BAD_REQUEST,
                              "%s 超出范围 %s..%s（收到 %s）" % (field, lower, upper, number))
    return number


def _as_float(value, lower, upper, default, field):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "%s 必须是数字" % field)
    number = float(value)
    if number < lower or number > upper:
        raise CWProtocolError(CWErrorCode.BAD_REQUEST,
                              "%s 超出范围 %s..%s（收到 %s）" % (field, lower, upper, number))
    return number


def _as_point(value, field):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "%s 必须是 [x, y]" % field)
    return [int(round(float(value[0]))), int(round(float(value[1])))]


def _normalize_swipe(step):
    out = {"action": "swipe"}
    out["duration_ms"] = _as_int(step.get("duration_ms"), 100, 2000, None, "duration_ms")
    direction = step.get("direction")
    if direction is not None:
        if direction not in SWIPE_DIRECTIONS:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST,
                                  "direction 只能是 %s" % "/".join(SWIPE_DIRECTIONS))
        out["direction"] = direction
        out["ratio"] = _as_float(step.get("ratio"), 0.05, 0.95, 0.5, "ratio")
        edge = step.get("edge")
        if edge is not None:
            if edge not in SWIPE_EDGES:
                raise CWProtocolError(CWErrorCode.BAD_REQUEST,
                                      "edge 只能是 %s" % "/".join(SWIPE_EDGES))
            out["edge"] = edge
        return out
    if step.get("from") is None or step.get("to") is None:
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "swipe 需要 direction+ratio 或 from+to")
    out["from"] = _as_point(step.get("from"), "from")
    out["to"] = _as_point(step.get("to"), "to")
    return out


def normalize_step(step):
    if not isinstance(step, dict):
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "step 必须是对象")
    name = step.get("action")
    spec = SPECS.get(name)
    if spec is None:
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "未知动作 %s" % name)
    if name == "swipe":
        return _normalize_swipe(step)
    for field in spec.required:
        if field not in step or step.get(field) is None:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "动作 %s 缺少 %s" % (name, field))
    out = {"action": name}
    for field in spec.point_fields:
        out[field] = _as_int(step.get(field), -10 ** 7, 10 ** 7, 0, field)
    for field, spec_range in spec.int_fields.items():
        out[field] = _as_int(step.get(field), spec_range[0], spec_range[1], spec_range[2], field)
    for field, spec_range in spec.num_fields.items():
        out[field] = _as_float(step.get(field), spec_range[0], spec_range[1], spec_range[2], field)
    for field in spec.str_fields:
        value = step.get(field)
        if not isinstance(value, str) or not value:
            raise CWProtocolError(CWErrorCode.BAD_REQUEST, "%s 必须是非空字符串" % field)
        out[field] = value
    if name == "press_key" and out.get("key") not in PRESS_KEYS:
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "不支持的按键 %s" % out.get("key"))
    if name in ("type_text", "paste_text") and len(out["text"]) > 2000:
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "文本过长")
    return out


def normalize_delay(value):
    if value is None:
        return MIN_DELAY_MS
    if isinstance(value, bool):
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "delay_ms 必须是整数")
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "delay_ms 必须是整数")
    return max(MIN_DELAY_MS, min(MAX_DELAY_MS, number))


def normalize_batch(steps, delay_ms=None, limit=MAX_STEPS_PER_BATCH):
    if not isinstance(steps, (list, tuple)) or not steps:
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "steps 必须是非空数组")
    if len(steps) > limit:
        raise CWProtocolError(CWErrorCode.BAD_REQUEST, "steps 最多 %d 个" % limit)
    return {"steps": [normalize_step(step) for step in steps], "delay_ms": normalize_delay(delay_ms)}


def point_steps(steps):
    points = []
    for step in steps:
        name = step.get("action")
        if name in ("tap", "long_press", "pinch"):
            points.append((step["x"], step["y"]))
        elif name == "swipe":
            points.append(tuple(step["from"]))
            points.append(tuple(step["to"]))
    return points


def describe(step):
    name = step.get("action")
    if name in ("tap", "long_press", "pinch"):
        return "%s(%s,%s)" % (name, step.get("x"), step.get("y"))
    if name == "swipe":
        if step.get("from") and step.get("to"):
            return "swipe(%s->%s)" % (step.get("from"), step.get("to"))
        if step.get("edge"):
            return "swipe(%s边缘 %s %s)" % (step.get("edge"), step.get("direction"), step.get("ratio"))
        return "swipe(%s %s)" % (step.get("direction"), step.get("ratio"))
    if name in ("type_text", "paste_text"):
        text = str(step.get("text", ""))
        return "%s(%s)" % (name, text[:16])
    if name in ("launch_app", "activate_app", "terminate_app"):
        return "%s(%s)" % (name, step.get("bundle_id"))
    if name == "press_key":
        return "press_key(%s)" % step.get("key")
    if name == "wait":
        return "wait(%sms)" % step.get("duration_ms")
    return str(name)


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])
