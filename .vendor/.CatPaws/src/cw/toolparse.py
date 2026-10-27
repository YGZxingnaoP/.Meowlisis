import json
import re

CW_TAG_RE = re.compile(r"<[^>]{0,300}>")
CW_INVOKE_RE = re.compile(r"invoke[^>]{0,80}?name\s*=\s*[\"']([A-Za-z0-9_]+)[\"']", re.I)
CW_PARAM_RE = re.compile(r"parameter[^>]{0,120}?name\s*=\s*[\"']([A-Za-z0-9_]+)[\"'][^>]{0,120}>([\s\S]*?)<",
                         re.I)


def strip_markup(text):
    """去掉正文里残留的调用标记，避免把 XML 当成人话念出来"""
    body = CW_TAG_RE.sub(" ", str(text or ""))
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _coerce(value):
    body = value.strip()
    if not body:
        return ""
    if body[0] in "{[":
        try:
            return json.loads(body)
        except Exception:
            return body
    low = body.lower()
    if low in ("true", "false"):
        return low == "true"
    if re.fullmatch(r"-?\d+", body):
        try:
            return int(body)
        except Exception:
            return body
    if re.fullmatch(r"-?\d+\.\d+", body):
        try:
            return float(body)
        except Exception:
            return body
    return body


def parse_tool_calls(content, known_names):
    """把「写在正文里的调用标记」解析成 [(name, args)]（模型不走 tool_calls 时兜底）"""
    text = str(content or "")
    marks = list(CW_INVOKE_RE.finditer(text))
    if not marks:
        return []
    known = set(known_names or [])
    calls = []
    for index, mark in enumerate(marks):
        name = mark.group(1)
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        segment = text[mark.end():end]
        if known and name not in known:
            continue
        args = {}
        for param in CW_PARAM_RE.finditer(segment):
            args[param.group(1)] = _coerce(param.group(2))
        calls.append((name, args))
    return calls
