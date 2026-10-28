import os
import tempfile

try:
    import yaml
except ImportError:
    yaml = None

CW_DEFAULT_SENSITIVE = ["支付", "密码", "验证码", "转账", "付款", "删除", "抹掉", "卸载", "格式化"]
CW_DEFAULT_DENY = ["com.apple.Preferences", "com.apple.Bridge", "com.apple.Passbook"]
CW_DEFAULT_REFLECT_BLOCK = ["支付", "付款", "转账", "密码", "验证码", "银行卡", "红包", "身份证",
                            "隐私", "删除", "卸载", "抹掉", "格式化"]


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


class CWConfig:
    """CatPaws 全部配置：唯一真值是 .vendor/.CatPaws/config.yml"""

    def __init__(self, config_path=None, section=None):
        self.here = os.path.dirname(os.path.abspath(__file__))
        self.catpaws_dir = os.path.dirname(os.path.dirname(self.here))
        self.project_dir = os.path.dirname(os.path.dirname(self.catpaws_dir))
        self.src_dir = os.path.dirname(self.here)
        self.actions_dir = os.path.join(self.catpaws_dir, "actions")
        self.web_dir = os.path.join(self.catpaws_dir, "web")
        self.log_dir = os.path.join(self.project_dir, "logs")
        self.ops_dir = os.path.join(self.log_dir, "catpaws_ops")
        self.thumb_dir = os.path.join(self.log_dir, "catpaws_thumbs")
        self.config_path = config_path or os.path.join(self.catpaws_dir, "config.yml")
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
        self.data = self.raw if section is None else _node(self.raw, section)

    def _apply(self):
        server = _node(self.data, "server")
        device = _node(self.data, "device")
        agent = _node(self.data, "agent")
        stream = _node(self.data, "stream")
        guard = _node(self.data, "guard")
        vision = _node(self.data, "vision")
        self.port_type = str(_pick(_node(self.data, "port"), "type", "deepseek") or "deepseek")

        self.host = str(_pick(server, "host", "127.0.0.1"))
        self.bind_host = str(_pick(server, "bind_host", self.host) or self.host)
        self.port = int(_pick(server, "port", 18110))
        self.relay_host = str(_pick(server, "relay_host", "0.0.0.0"))
        self.relay_port = int(_pick(server, "relay_port", 18111))
        self.token = str(_pick(server, "token", "") or "")

        self.device_ip = str(_pick(device, "ip", "127.0.0.1"))
        self.device_port = int(_pick(device, "port", 8100))
        self.device_timeout = float(_pick(device, "timeout", 10))
        self.mock = bool(_pick(device, "mock", False))
        self.mock_fallback = bool(_pick(device, "mock_fallback", False))
        self.runner_bundle_id = str(_pick(device, "runner_bundle_id", ""))
        self.app_bundle_id = str(_pick(device, "catcam_bundle_id", ""))

        self.allow_ocr = bool(_pick(agent, "allow_ocr", True))
        self.min_delay_ms = int(_pick(agent, "min_delay_ms", 90))
        self.sequence_steps = int(_pick(agent, "sequence_steps", 10))
        self.max_steps_per_session = int(_pick(agent, "max_steps_per_session", 0))
        self.max_actions_per_second = float(_pick(agent, "max_actions_per_second", 5))
        self.session_timeout_sec = int(_pick(agent, "session_timeout_sec", 0))
        self.action_timeout_sec = int(_pick(agent, "action_timeout_sec", 120))
        self.ask_timeout_sec = int(_pick(agent, "ask_timeout_sec", 150))
        self.agent_max_rounds = int(_pick(agent, "max_rounds", 0))
        self.bridge_lost_sec = int(_pick(agent, "bridge_lost_sec", 60))
        self.start_home = bool(_pick(agent, "start_home", True))
        self.exit_to_home = bool(_pick(agent, "exit_to_home", False))
        self.reflect_enabled = bool(_pick(agent, "reflect_enabled", True))
        self.reflect_max_rounds = int(_pick(agent, "reflect_max_rounds", 12))
        self.action_max_files = int(_pick(agent, "action_max_files", 5))
        self.action_max_bytes = int(_pick(agent, "action_max_bytes", 200000))
        self.action_max_change_lines = int(_pick(agent, "action_max_change_lines", 60))
        self.thumb_enabled = bool(_pick(agent, "thumb_enabled", True))
        self.thumb_long_edge = int(_pick(agent, "thumb_long_edge", 320))
        self.thumb_quality = int(_pick(agent, "thumb_quality", 60))
        self.keep_awake_sec = int(_pick(agent, "keep_awake_sec", 30) or 0)
        self.keep_awake_point = []
        for item in _as_list(_pick(agent, "keep_awake_point", None), []):
            try:
                self.keep_awake_point.append(int(float(item)))
            except (TypeError, ValueError):
                continue
        self.screenshot_max_edge = int(_pick(agent, "screenshot_max_edge", 1280))
        self.swipe_min_px = int(_pick(agent, "swipe_min_px", 90))
        self.swipe_margin_px = int(_pick(agent, "swipe_margin_px", 60))
        self.swipe_speed_px_ms = float(_pick(agent, "swipe_speed_px_ms", 4.0))
        self.tap_margin_px = int(_pick(agent, "tap_margin_px", 8))

        self.stream_fps = int(_pick(stream, "fps", 10))
        self.stream_max_edge = int(_pick(stream, "max_edge", 1280))
        self.stream_bitrate = int(_pick(stream, "bitrate", 1500000))

        self.app_allowlist = _as_list(_pick(guard, "app_allowlist", None), [])
        self.app_denylist = _as_list(_pick(guard, "app_denylist", None), CW_DEFAULT_DENY)
        self.apps = {}
        raw_apps = _node(guard, "apps")
        for name, bundle in raw_apps.items():
            self.apps[str(name)] = str(bundle)
        self.sensitive_words = _as_list(_pick(guard, "sensitive_words", None), CW_DEFAULT_SENSITIVE)
        self.sensitive_confirm = bool(_pick(guard, "sensitive_confirm", False))
        self.reflect_block_words = _as_list(_pick(guard, "reflect_block_words", None),
                                            CW_DEFAULT_REFLECT_BLOCK)

        self.vision_base_url = str(_pick(vision, "base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
        self.vision_api_key = str(_pick(vision, "api_key", "") or "")
        self.vision_model = str(_pick(vision, "model", "qwen-vl-max"))
        self.vision_max_edge = int(_pick(vision, "max_edge", 1024))

        port_block = _node(_node(self.data, "port"), self.port_type)
        self.llm_base_url = str(_pick(port_block, "base_url", "https://api.deepseek.com/v1"))
        self.llm_api_key = str(_pick(port_block, "api_key", "") or "")
        self.llm_model = str(_pick(port_block, "model", "deepseek-chat"))
        self.llm_temperature = float(_pick(port_block, "temperature", 0.6))
        self.llm_max_tokens = int(_pick(port_block, "max_tokens", 4096))
        self.port_options = dict(port_block)
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
            "host": self.host, "bind_host": self.bind_host, "port": self.port,
            "relay_port": self.relay_port,
            "device": {"ip": self.device_ip, "port": self.device_port, "mock": self.mock,
                       "start_home": self.start_home, "exit_to_home": self.exit_to_home},
            "keep_awake": {"sec": self.keep_awake_sec, "point": list(self.keep_awake_point)},
            "allow_ocr": self.allow_ocr,
            "stream": {"fps": self.stream_fps, "max_edge": self.stream_max_edge,
                       "bitrate": self.stream_bitrate},
            "llm": {"type": self.port_type, "model": self.llm_model,
                    "vision_model": self.vision_model, "has_key": bool(self.llm_api_key)},
            "reflect": {"enabled": self.reflect_enabled, "max_rounds": self.reflect_max_rounds},
        }
