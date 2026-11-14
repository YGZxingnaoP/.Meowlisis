# -*- coding: utf-8 -*-
# scripts/MossLive-test/mosslive/config.py
# 测试配置加载：config.json 与内置默认值深度合并。
# 路径分两套解析：
#   - project_path：相对项目根目录（D:\.Meowlisis），用于引用角色卡、提示词、参考音频；
#   - local_path：相对本测试目录（scripts/MossLive-test），用于写缓存、便签、转录等测试产物。

import copy
import json
import os
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SCRIPT_DIR.parents[1]


class ConfigError(Exception):
    """配置错误（缺字段、取值非法、密钥缺失）"""


DEFAULTS = {
    "api": {
        "realtime_url": "wss://api.mosi.cn/v1/realtime",
        "http_base": "https://api.mosi.cn",
        "api_key": "",
        "api_key_env": "MOSS_API_KEY",
        "model": "moss-live-1.0",
        "user": "meowlisis-desktop",
        "proxy": None,
        "connect_timeout_sec": 20,
    },
    "session": {
        "memory_scope": "session",
        "playback": "client",
        "profile": "standard",
        "output_audio": {"format": "pcm16", "sample_rate": 48000},
        "input_audio": {"format": "pcm16"},
        "video": {"max_long_side": 512, "jpeg_quality": 0.75, "interval_ms": 1000},
        "time_zone": "Asia/Shanghai",
        "location": None,
    },
    "prompt": {
        "mode": "project",
        "persona_name": "",
        "persona_inline": "",
        "display_name": "主人",
        "card_file": "",
        "include_front_prompt": True,
        "include_active_prompt": False,
        "include_values": True,
        "extra_sources": [],
        "instructions": "",
        "instructions_files": [],
        "max_persona_chars": 8000,
        "max_instructions_chars": 16000,
    },
    "voice": {
        "mode": "clone",
        "name": "",
        "fallback_name": "6c3152b1-1d4f-4e49-ade3-09f447712fec",
        "ref_audio": {
            "source": "character/ref_audio/config.json",
            "character": "",
            "emotion": "neutral",
            "file": "",
        },
        "clone": {
            "voice_name": "meowlisis-mosslive-test",
            "cache_file": "voice_cache.json",
            "recreate": False,
            "max_seconds": 29,
        },
    },
    "audio": {
        "input_device": -1,
        "output_device": -1,
        "input_rate": 16000,
        "output_rate": 48000,
        "frame_ms": 20,
        "input_enabled": True,
        "output_enabled": True,
        "volume": 1.0,
    },
    "screen": {
        "enabled": True,
        "monitor": 1,
        "region": None,
        "interval_ms": 1000,
        "max_long_side": 512,
        "jpeg_quality": 0.75,
        "save_frames": False,
        "frames_dir": "frames",
    },
    "tools": {
        "enabled": [
            "get_time",
            "open_url",
            "list_windows",
            "activate_window",
            "save_note",
            "search_files",
        ],
        "search_root": "",
        "search_max_results": 20,
        "notes_file": "notes/notes.md",
    },
    "log": {
        "level": "INFO",
        "save_events": True,
        "sessions_dir": "sessions",
        "verbose_events": False,
        "show_partial": False,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并配置；override 的标量与列表整体覆盖 base"""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class TestConfig:
    """测试配置：读取 config.json，补齐默认值，并提供路径/密钥解析"""

    def __init__(self, data: dict, path: Path):
        self.data = data
        self.path = Path(path)
        self.script_dir = SCRIPT_DIR
        self.project_root = PROJECT_ROOT
        self.api = data["api"]
        self.session = data["session"]
        self.prompt = data["prompt"]
        self.voice = data["voice"]
        self.audio = data["audio"]
        self.screen = data["screen"]
        self.tools = data["tools"]
        self.log = data["log"]

    @classmethod
    def load(cls, path=None) -> "TestConfig":
        cfg_path = Path(path).resolve() if path else (SCRIPT_DIR / "config.json")
        if not cfg_path.exists():
            raise ConfigError(f"配置文件不存在: {cfg_path}")
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"配置文件 JSON 解析失败（{cfg_path}）: {e}") from e
        if not isinstance(raw, dict):
            raise ConfigError("config.json 顶层必须是对象")
        cfg = cls(_deep_merge(DEFAULTS, raw), cfg_path)
        cfg.validate()
        return cfg

    # ---------- 路径 ----------

    def project_path(self, value) -> Path:
        """项目根相对路径解析（绝对路径原样返回）"""
        p = Path(str(value))
        return p if p.is_absolute() else (self.project_root / p)

    def local_path(self, value) -> Path:
        """测试目录相对路径解析（绝对路径原样返回）"""
        p = Path(str(value))
        return p if p.is_absolute() else (self.script_dir / p)

    @property
    def api_key(self) -> str:
        """密钥优先取 config.json，其次取环境变量"""
        key = str(self.api.get("api_key") or "").strip()
        if key:
            return key
        env_name = str(self.api.get("api_key_env") or "").strip()
        if env_name:
            return str(os.environ.get(env_name, "") or "").strip()
        return ""

    def key_hint(self) -> str:
        """缺密钥时给出的操作提示"""
        env_name = str(self.api.get("api_key_env") or "MOSS_API_KEY").strip()
        return (
            f"未找到 MOSS API Key。请编辑 {self.path} 的 api.api_key，"
            f"或设置环境变量 {env_name}。"
        )

    # ---------- 校验 ----------

    def validate(self):
        rt = str(self.api.get("realtime_url") or "")
        if not rt.startswith(("ws://", "wss://")):
            raise ConfigError(f"api.realtime_url 必须是 ws/wss 地址: {rt!r}")
        if not str(self.api.get("model") or "").strip():
            raise ConfigError("api.model 不能为空")
        if str(self.prompt.get("mode")) not in ("project", "files", "inline"):
            raise ConfigError("prompt.mode 只能是 project / files / inline")
        if str(self.voice.get("mode")) not in ("clone", "name", "default"):
            raise ConfigError("voice.mode 只能是 clone / name / default")
        if str(self.session.get("playback")) not in ("client", "server"):
            raise ConfigError("session.playback 只能是 client / server")
        frame_ms = int(self.audio.get("frame_ms") or 20)
        if not 5 <= frame_ms <= 100:
            raise ConfigError("audio.frame_ms 需在 5~100 之间")
        volume = float(self.audio.get("volume") if self.audio.get("volume") is not None else 1.0)
        if not 0.0 <= volume <= 3.0:
            raise ConfigError("audio.volume 需在 0~3 之间")
        interval = int(self.screen.get("interval_ms") or 1000)
        if not 200 <= interval <= 10000:
            raise ConfigError("screen.interval_ms 需在 200~10000 之间（接口下限 200）")
        long_side = int(self.screen.get("max_long_side") or 512)
        if not 128 <= long_side <= 1920:
            raise ConfigError("screen.max_long_side 需在 128~1920 之间")
        quality = float(self.screen.get("jpeg_quality") or 0.75)
        if not 0.1 <= quality <= 1.0:
            raise ConfigError("screen.jpeg_quality 需在 0.1~1.0 之间")

    def require_api_key(self) -> str:
        key = self.api_key
        if not key:
            raise ConfigError(self.key_hint())
        return key

    # ---------- 展示 ----------

    def summary(self) -> str:
        """一行摘要，启动时打印"""
        out_fmt = self.session.get("output_audio") or {}
        screen = "开" if self.screen.get("enabled") else "关"
        mic = "开" if self.audio.get("input_enabled") else "关"
        return (
            f"模型={self.api.get('model')} 音色模式={self.voice.get('mode')} "
            f"麦克风={mic} 屏幕={screen}({self.screen.get('max_long_side')}px/"
            f"{self.screen.get('interval_ms')}ms) 下行={out_fmt.get('format')}@"
            f"{out_fmt.get('sample_rate')}Hz 工具={len(self.tools.get('enabled') or [])}个"
        )


def get_nested(data: dict, dotted: str):
    """给外部模块复用的嵌套取值"""
    return _nested_get(data, dotted)
