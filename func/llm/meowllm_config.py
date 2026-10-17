# -*- coding: utf-8 -*-

import os
import threading

import yaml

_LOCK = threading.RLock()
_CACHE = {"mtime": None, "data": {}}

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(_ROOT, ".vendor", ".MeowLLM", "config.yml")


def config_path():
    return CONFIG_PATH


def _read():
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    node = raw.get("meowllm") or {}
    return node if isinstance(node, dict) else {}


def data(force=False):
    with _LOCK:
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
        except OSError:
            return {}
        if force or _CACHE["mtime"] != mtime:
            _CACHE["data"] = _read()
            _CACHE["mtime"] = mtime
        return _CACHE["data"]


def get(dotted, default=None):
    node = data()
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def base_url():
    host = str(get("server.host", "127.0.0.1"))
    port = int(get("server.port", 18100))
    try:
        state_dir = get("paths.state_dir", ".test/state/meowllm")
        path = os.path.join(_ROOT, ".vendor", ".MeowLLM", str(state_dir), "port.json")
        if os.path.isfile(path):
            import json
            with open(path, "r", encoding="utf-8") as fh:
                info = json.load(fh)
            live = int(info.get("port") or 0)
            if live:
                host = str(info.get("host") or host)
                port = live
    except Exception:
        pass
    return f"http://{host}:{port}/meowllm/v1"


def model_name():
    return str(get("model.name", "meowllm-local"))


def gen(key, default=None):
    return get(f"gen.{key}", default)


def thinking_level():
    return str(get("thinking.default_level", "off"))


def conversation_tokens():
    return int(get("context.n_ctx", 8192))


def reload():
    with _LOCK:
        _CACHE["mtime"] = None
    return data(force=True)


def save(node):
    with _LOCK:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        raw["meowllm"] = node
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            yaml.safe_dump(raw, fh, allow_unicode=True, sort_keys=False)
        _CACHE["mtime"] = None
    return data(force=True)
