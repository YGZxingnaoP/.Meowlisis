# -*- coding: utf-8 -*-
# func/catpaws/config.py
# catpaws 配置：唯一真值是 .vendor/.CatPaws/config.yml（不读主项目 config.yml）
import os
import threading

try:
    import yaml
except ImportError:
    yaml = None

from func.tools.singleton_mode import singleton

CW_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CW_CONFIG_PATH = os.path.join(CW_PROJECT_DIR, ".vendor", ".CatPaws", "config.yml")

CW_DEFAULT_PREFIX = ["喵呜我要点外卖"]
CW_DEFAULT_INTENT = ["手机"]
CW_DEFAULT_STOP = ["别再操控手机了", "手机还我"]


def _node(data, key):
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _pick(data, key, default):
    value = data.get(key, default)
    return default if value is None else value


def _as_list(value, default):
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return list(default)


@singleton
class CWCatPawsConfig:
    """catpaws 配置管理：读取 .vendor/.CatPaws/config.yml，支持运行中热更新"""

    def __init__(self):
        self.path = CW_CONFIG_PATH
        self._lock = threading.RLock()
        self._mtime = 0.0
        self._data = {}
        self._apply({})
        self.refresh(force=True)

    def _stat(self):
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0.0

    def refresh(self, force=False):
        """配置文件变化时重新读取（GUI 改完配置不用重启主程序）"""
        with self._lock:
            mtime = self._stat()
            if not force and mtime and mtime == self._mtime:
                return False
            data = {}
            if yaml is not None and os.path.exists(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as handle:
                        root = yaml.safe_load(handle) or {}
                    data = root if isinstance(root, dict) else {}
                except Exception:
                    data = {}
            self._mtime = mtime
            self._data = data
            self._apply(data)
            return True

    def _apply(self, data):
        trigger = _node(data, "trigger")
        stop = _node(data, "stop")
        server = _node(data, "server")
        device = _node(data, "device")
        sync = _node(data, "sync")
        port = _node(data, "port")
        self.enabled = bool(_pick(trigger, "enabled", True))
        self.allow_mock = bool(_pick(device, "allow_mock", False))
        self.trigger_mode = str(_pick(trigger, "trigger_mode", "both") or "both").strip()
        self.prefixes = _as_list(_pick(trigger, "prefix", None), CW_DEFAULT_PREFIX)
        self.intent_words = _as_list(_pick(trigger, "intent", None), CW_DEFAULT_INTENT)
        self.intent_prompt = str(_pick(trigger, "prompt", "") or "")
        self.stop_keywords = _as_list(_pick(stop, "keywords", None), CW_DEFAULT_STOP)
        self.host = str(_pick(server, "host", "127.0.0.1"))
        self.port = int(_pick(server, "port", 18110))
        self.token = str(_pick(server, "token", "") or "")
        self.timeout = float(_pick(sync, "timeout", 8))
        self.poll_sec = float(_pick(sync, "poll_sec", 1.0) or 1.0)
        self.max_run_sec = int(_pick(sync, "max_run_sec", 0) or 0)
        self.answer_timeout = int(_pick(sync, "answer_timeout", 150) or 0)
        self.notify = bool(_pick(sync, "notify", True))
        self.short_rounds = int(_pick(sync, "short_rounds", 12) or 0)
        self.port_type = str(_pick(port, "type", "deepseek") or "deepseek").strip().lower()
        self.port_options = dict(_node(port, self.port_type))

    def base_url(self):
        return "http://%s:%d" % (self.host, self.port)

    def headers(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer %s" % self.token
        return headers
