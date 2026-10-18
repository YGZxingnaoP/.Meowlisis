# -*- coding: utf-8 -*-
# func/meowllm/config.py
"""读写 `.vendor/.MeowLLM/config.yml` 里的 `meowllm` 节点。

**这是唯一的读取入口**：所有模块的 meowllm 端口都从这里拿端点/模型名/采样参数，
不要各自去 yaml.load 一遍，否则又会出现"两份配置打架"。
（本文件由 func/llm/meowllm_config.py 迁移而来，行为不变。）
"""

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
    """OpenAI 兼容端点：`http://host:port/meowllm/v1`。

    端口以 `paths.state_dir/port.json` 里的**真实端口**为准（服务可能因为
    18100 被占用而回退），所以改端口不需要改这里。
    """
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


def save(node):
    """整体替换 config.yml 里的 meowllm 节点。

    注意：`yaml.safe_dump` 会**丢掉原文件里的注释**（PyYAML 的固有行为）。
    所以每次写之前留一份 `config.yml.bak`，误存了能立刻回滚。
    """
    if not isinstance(node, dict):
        raise ValueError("meowllm 配置必须是一个映射（dict）")
    with _LOCK:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        try:
            import shutil

            shutil.copy2(CONFIG_PATH, CONFIG_PATH + ".bak")
        except OSError:
            pass
        raw["meowllm"] = node
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            yaml.safe_dump(raw, fh, allow_unicode=True, sort_keys=False)
        _CACHE["mtime"] = None
    return data(force=True)
