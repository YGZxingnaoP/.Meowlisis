# -*- coding: utf-8 -*-

from __future__ import annotations

import copy
import os
import re
from typing import Any

from meowllm.errors import MeowLLMConfigError

_ENV_PREFIX = "MEOWLLM__"
_ENV_EXPAND = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

DEFAULT_CONFIG: dict = {
    "server": {
        "host": "127.0.0.1",
        "port": 18100,
        "port_fallback": 9,
        "request_timeout": 120,
    },
    "model": {
        "name": "meowllm-local",
    },
    "context": {
        "n_ctx": 8192,
        "n_threads": 0,
        "max_prompt_tokens": 4096,
        "dual_max_prompt_tokens": 2048,
    },
    "gen": {
        "temperature": 0.8,
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.05,
        "stop": [],
        "seed": None,
        "talk_max_tokens": 256,
    },
    "engine": {
        "kind": "dualstream",
        "dualstream": {
            "model_dir": "models/Qwen3-0.6B",
            "device": "cuda",
            "dtype": "bfloat16",
            "language": "en",
            "probe_every_tokens": 20,
            "max_segments": 6,
            "stop_after_no": 2,
            "probe_kind": "roleplay",
            "fast_prefill": True,
        },
    },
    "safety": {
        "allow_engine": ["dualstream"],
        "max_local_model_params_b": 1.0,
        "require_env_override": False,
    },
    "thinking": {
        "default_level": "off",
        "budgets": {"off": 0, "low": 256, "medium": 768, "high": 2048},
        "force_off_when_tools": True,
    },
    "cache": {
        "prefix": {
            "enabled": True,
            "slots": 4,
            "min_prefix_tokens": 256,
            "volatile_markers": ["# 现在是", "我心里装着的", "# 当前情绪"],
        },
        "session": {
            "enabled": True,
            "max_sessions": 8,
            "ttl_seconds": 3600,
        },
    },
    "queue": {
        "max_concurrency": 1,
        "interactive_first": True,
    },
    "paths": {
        "state_dir": ".test/state/meowllm",
        "log_dir": ".test/logs",
    },
}

_THINKING_LEVELS = ("off", "low", "medium", "high")
_DEVICES = ("cuda", "cpu")
_DTYPES = ("bfloat16", "float16", "float32")


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_EXPAND.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _coerce(raw: str) -> Any:
    text = raw.strip()
    low = text.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", ""):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _apply_env_overrides(cfg: dict) -> dict:
    for name, value in os.environ.items():
        if not name.startswith(_ENV_PREFIX):
            continue
        path = [p.lower() for p in name[len(_ENV_PREFIX):].split("__") if p]
        if not path:
            continue
        node = cfg
        for part in path[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                break
        else:
            node[path[-1]] = _coerce(value)
    if os.environ.get("MEOWLLM_STATE_DIR"):
        cfg.setdefault("paths", {})["state_dir"] = os.environ["MEOWLLM_STATE_DIR"]
    if os.environ.get("MEOWLLM_LOG_DIR"):
        cfg.setdefault("paths", {})["log_dir"] = os.environ["MEOWLLM_LOG_DIR"]
    return cfg


def _fix_yaml_bools(cfg: dict) -> dict:
    thinking = cfg.get("thinking")
    if not isinstance(thinking, dict):
        return cfg

    budgets = thinking.get("budgets")
    if isinstance(budgets, dict):
        fixed: dict = {}
        for key, value in budgets.items():
            if key is False:
                key = "off"
            elif key is True:
                key = "on"
            fixed[str(key)] = value
        thinking["budgets"] = fixed

    for field in ("default_level",):
        value = thinking.get(field)
        if value is False:
            thinking[field] = "off"
        elif value is True:
            thinking[field] = "on"
    return cfg


class MeowLLMConfig:
    def __init__(self, data: dict, source: str = "<defaults>"):
        self._data = data
        self.source = source

    @classmethod
    def load(cls, path: str | None = None) -> "MeowLLMConfig":
        import yaml

        cfg_path = path or os.environ.get("MEOWLLM_CONFIG") or cls.default_path()
        user: dict = {}
        if cfg_path and os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
            except Exception as exc:
                raise MeowLLMConfigError(f"读取配置失败 {cfg_path}: {exc}") from exc
            if not isinstance(raw, dict):
                raise MeowLLMConfigError(f"配置根节点必须是映射: {cfg_path}")
            if "meowllm" not in raw:
                raise MeowLLMConfigError(
                    f"配置根键必须是 meowllm:（当前根键 {list(raw)[:5]}）: {cfg_path}")
            user = raw["meowllm"] or {}
            if not isinstance(user, dict):
                raise MeowLLMConfigError("meowllm: 节点必须是映射")
        elif path:
            raise MeowLLMConfigError(f"配置文件不存在: {cfg_path}")

        data = _deep_merge(DEFAULT_CONFIG, user)
        data = _expand_env(data)
        data = _apply_env_overrides(data)
        data = _fix_yaml_bools(data)
        conf = cls(data, source=cfg_path or "<defaults>")
        conf.validate()
        return conf

    @staticmethod
    def default_path() -> str:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(here, "config.yml")

    @property
    def data(self) -> dict:
        return self._data

    def section(self, name: str) -> dict:
        node = self._data.get(name)
        return node if isinstance(node, dict) else {}

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def root(self) -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def resolve(self, relative: str) -> str:
        if not relative:
            return ""
        if os.path.isabs(relative):
            return relative
        return os.path.normpath(os.path.join(self.root, relative))

    @property
    def state_dir(self) -> str:
        return self.resolve(self.get("paths.state_dir", ".test/state/meowllm"))

    @property
    def log_dir(self) -> str:
        return self.resolve(self.get("paths.log_dir", ".test/logs"))

    def validate(self) -> None:
        problems: list[str] = []

        host = str(self.get("server.host", "127.0.0.1")).strip()
        if host not in ("127.0.0.1", "localhost", "::1"):
            problems.append(f"server.host 必须是回环地址（当前 {host!r}）")

        port = self.get("server.port", 18100)
        if not isinstance(port, int) or not (1024 <= port <= 65535):
            problems.append(f"server.port 非法: {port!r}")

        fallback = self.get("server.port_fallback", 0)
        if not isinstance(fallback, int) or fallback < 0 or fallback > 64:
            problems.append(f"server.port_fallback 非法: {fallback!r}")

        allow = self.get("safety.allow_engine", [])
        if not isinstance(allow, list) or not allow:
            problems.append("safety.allow_engine 必须是非空列表")

        kind = self.get("engine.kind")
        if allow and kind not in allow:
            problems.append(
                f"engine.kind={kind!r} 不在 safety.allow_engine={allow} 白名单里")

        budgets = self.get("thinking.budgets", {})
        if not isinstance(budgets, dict) or set(budgets) - set(_THINKING_LEVELS):
            problems.append(f"thinking.budgets 键只能是 {_THINKING_LEVELS}: {budgets!r}")
        elif budgets.get("off", 0) != 0:
            problems.append("thinking.budgets.off 必须为 0")

        level = self.get("thinking.default_level", "off")
        if level not in _THINKING_LEVELS:
            problems.append(f"thinking.default_level 非法: {level!r}")

        n_ctx = self.get("context.n_ctx", 0)
        if not isinstance(n_ctx, int) or n_ctx < 1024:
            problems.append(f"context.n_ctx 必须 >= 1024: {n_ctx!r}")

        for key in ("talk_max_tokens",):
            value = self.get(f"gen.{key}", 0)
            if not isinstance(value, int) or value <= 0:
                problems.append(f"gen.{key} 必须 > 0: {value!r}")
            elif isinstance(n_ctx, int) and value >= n_ctx:
                problems.append(f"gen.{key}({value}) 必须小于 context.n_ctx({n_ctx})")

        max_params = self.get("safety.max_local_model_params_b", 1.0)
        if not isinstance(max_params, (int, float)) or max_params <= 0:
            problems.append(f"safety.max_local_model_params_b 非法: {max_params!r}")

        if kind == "dualstream":
            if not self.get("engine.dualstream.model_dir"):
                problems.append("engine.kind=dualstream 时 engine.dualstream.model_dir 不能为空")
            device = str(self.get("engine.dualstream.device", "cuda"))
            if device not in _DEVICES:
                problems.append(f"engine.dualstream.device 只能是 {_DEVICES}: {device!r}")
            dtype = str(self.get("engine.dualstream.dtype", "bfloat16"))
            if dtype not in _DTYPES:
                problems.append(f"engine.dualstream.dtype 只能是 {_DTYPES}: {dtype!r}")
            probe = str(self.get("engine.dualstream.probe_kind", "roleplay"))
            if probe not in ("roleplay", "math"):
                problems.append(f"engine.dualstream.probe_kind 只能是 roleplay/math: {probe!r}")
            segments = self.get("engine.dualstream.max_segments", 6)
            if not isinstance(segments, int) or not (1 <= segments <= 32):
                problems.append(f"engine.dualstream.max_segments 必须在 [1,32]: {segments!r}")
            stop_no = self.get("engine.dualstream.stop_after_no", 2)
            if not isinstance(stop_no, int) or not (1 <= stop_no <= 8):
                problems.append(f"engine.dualstream.stop_after_no 必须在 [1,8]: {stop_no!r}")

        for key in ("temperature", "top_p"):
            value = self.get(f"gen.{key}", 0)
            if not isinstance(value, (int, float)):
                problems.append(f"gen.{key} 必须是数字: {value!r}")

        if problems:
            raise MeowLLMConfigError(
                "配置校验未通过：" + "；".join(problems), detail=problems)

    def ensure_dirs(self) -> list[str]:
        failed = []
        for path in (self.state_dir, self.log_dir):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception:
                failed.append(path)
        return failed

    def dump_safe(self) -> dict:
        return {
            "source": self.source,
            "server": {"host": self.get("server.host"), "port": self.get("server.port")},
            "engine": self.get("engine.kind"),
            "model": {
                "name": self.get("model.name"),
                "dir": os.path.basename(
                    self.get("engine.dualstream.model_dir") or ""),
            },
            "safety": {
                "allow_engine": self.get("safety.allow_engine"),
                "max_local_model_params_b": self.get("safety.max_local_model_params_b"),
            },
            "context": {"n_ctx": self.get("context.n_ctx")},
            "gen": {
                "talk_max_tokens": self.get("gen.talk_max_tokens"),
                "temperature": self.get("gen.temperature"),
                "top_p": self.get("gen.top_p"),
                "top_k": self.get("gen.top_k"),
            },
            "thinking": {
                "default_level": self.get("thinking.default_level"),
                "budgets": self.get("thinking.budgets"),
            },
        }
