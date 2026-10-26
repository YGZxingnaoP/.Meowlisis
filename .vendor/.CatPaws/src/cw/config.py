import os
import tempfile

try:
    import yaml
except ImportError:
    yaml = None


def _dir_writable(path):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_probe")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _ensure_writable(path, name):
    if _dir_writable(path):
        return path
    fallback = os.path.join(tempfile.gettempdir(), "catpaws", name)
    os.makedirs(fallback, exist_ok=True)
    return fallback

CW_DEFAULT_SENSITIVE = ["支付", "密码", "验证码", "转账", "付款", "删除", "抹掉", "卸载", "格式化"]
CW_DEFAULT_DENY = ["com.apple.Preferences", "com.apple.Bridge", "com.apple.Passbook"]


class CWConfig:
    def __init__(self, config_path=None, section="catpaws"):
        self.here = os.path.dirname(os.path.abspath(__file__))
        self.catpaws_dir = os.path.dirname(os.path.dirname(self.here))
        self.project_dir = os.path.dirname(os.path.dirname(self.catpaws_dir))
        self.src_dir = os.path.dirname(self.here)
        self.actions_dir = os.path.join(self.catpaws_dir, "actions")
        self.web_dir = os.path.join(self.catpaws_dir, "web")
        self.log_dir = os.path.join(self.project_dir, "logs")
        self.ops_dir = os.path.join(self.log_dir, "catpaws_ops")
        self.thumb_dir = os.path.join(self.log_dir, "catpaws_thumbs")
        self.config_path = config_path or os.path.join(self.project_dir, "config.yml")
        self.data = {}
        self.raw = {}
        self._load(section)
        self._apply()

    def _load(self, section):
        if yaml is None or not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as handle:
                root = yaml.safe_load(handle) or {}
        except Exception:
            root = {}
        self.raw = root if isinstance(root, dict) else {}
        node = self.raw.get(section) or {}
        self.data = node if isinstance(node, dict) else {}

    def _get(self, key, default):
        value = self.data.get(key, default)
        return default if value is None else value

    def _apply(self):
        self.enabled = bool(self._get("enabled", True))
        self.host = str(self._get("host", "127.0.0.1"))
        self.port = int(self._get("port", 18110))
        self.relay_host = str(self._get("relay_host", "0.0.0.0"))
        self.relay_port = int(self._get("relay_port", 18111))
        self.token = str(self._get("token", "") or "")
        self.device_ip = str(self._get("device_ip", "127.0.0.1"))
        self.device_port = int(self._get("device_port", 8100))
        self.device_timeout = float(self._get("device_timeout", 8))
        self.mock = bool(self._get("mock", False))
        self.allow_ocr = bool(self._get("allow_ocr", True))
        self.runner_bundle_id = str(self._get("runner_bundle_id", ""))
        self.app_bundle_id = str(self._get("app_bundle_id", ""))
        self.min_delay_ms = int(self._get("min_delay_ms", 90))
        self.sequence_steps = int(self._get("sequence_steps", 20))
        self.max_steps_per_session = int(self._get("max_steps_per_session", 200))
        self.max_actions_per_second = float(self._get("max_actions_per_second", 5))
        self.session_timeout_sec = int(self._get("session_timeout_sec", 900))
        self.action_timeout_sec = int(self._get("action_timeout_sec", 120))
        self.ask_timeout_sec = int(self._get("ask_timeout_sec", 60))
        self.agent_max_rounds = int(self._get("agent_max_rounds", 0))
        self.reflect_enabled = bool(self._get("reflect_enabled", True))
        self.reflect_max_rounds = int(self._get("reflect_max_rounds", 4))
        self.action_max_files = int(self._get("action_max_files", 5))
        self.action_max_bytes = int(self._get("action_max_bytes", 200000))
        self.action_max_change_lines = int(self._get("action_max_change_lines", 60))
        self.thumb_enabled = bool(self._get("thumb_enabled", True))
        self.thumb_long_edge = int(self._get("thumb_long_edge", 320))
        self.thumb_quality = int(self._get("thumb_quality", 60))
        self.screenshot_max_edge = int(self._get("screenshot_max_edge", 1280))
        self.exit_to_home = bool(self._get("exit_to_home", True))
        self.sensitive_confirm = bool(self._get("sensitive_confirm", False))
        self.swipe_min_px = int(self._get("swipe_min_px", 90))
        self.swipe_margin_px = int(self._get("swipe_margin_px", 60))
        self.swipe_speed_px_ms = float(self._get("swipe_speed_px_ms", 1.2))
        self.tap_margin_px = int(self._get("tap_margin_px", 8))
        allow = self._get("app_allowlist", []) or []
        deny = self._get("app_denylist", None)
        self.app_allowlist = [str(item) for item in allow]
        self.app_denylist = [str(item) for item in (deny if deny is not None else CW_DEFAULT_DENY)]
        apps = self._get("apps", {}) or {}
        self.apps = {}
        if isinstance(apps, dict):
            for name, bundle in apps.items():
                self.apps[str(name)] = str(bundle)
        words = self._get("sensitive_words", None)
        self.sensitive_words = [str(item) for item in (words if words is not None else CW_DEFAULT_SENSITIVE)]
        self.stream_fps = int(self._get("stream_fps", 10))
        self.stream_max_edge = int(self._get("stream_max_edge", 1280))
        self.stream_bitrate = int(self._get("stream_bitrate", 1500000))
        llm = self._get("llm", {}) or {}
        self.llm_base_url = str(llm.get("base_url", "https://api.deepseek.com/v1"))
        self.llm_api_key = str(llm.get("api_key", "") or "")
        self.llm_model = str(llm.get("model", "deepseek-chat"))
        self.llm_temperature = float(llm.get("temperature", 0.2))
        self.llm_max_tokens = int(llm.get("max_tokens", 2048))
        self.vision_base_url = str(llm.get("vision_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
        self.vision_api_key = str(llm.get("vision_api_key", "") or "")
        self.vision_model = str(llm.get("vision_model", "qwen-vl-max"))
        self.actions_writable = True

    def ensure_dirs(self):
        self.ops_dir = _ensure_writable(self.ops_dir, "catpaws_ops")
        self.thumb_dir = _ensure_writable(self.thumb_dir, "catpaws_thumbs")
        self.actions_writable = _dir_writable(self.actions_dir)

    def ops_log_path(self):
        import datetime
        day = datetime.date.today().strftime("%Y-%m-%d")
        return os.path.join(self.ops_dir, "ops_%s.jsonl" % day)

    def as_public(self):
        return {
            "host": self.host, "port": self.port,
            "relay_port": self.relay_port,
            "device": {"ip": self.device_ip, "port": self.device_port, "mock": self.mock},
            "allow_ocr": self.allow_ocr,
            "stream": {"fps": self.stream_fps, "max_edge": self.stream_max_edge, "bitrate": self.stream_bitrate},
            "llm": {"model": self.llm_model, "vision_model": self.vision_model,
                    "has_key": bool(self.llm_api_key)},
        }
