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
            #: 每 N 个 decode step 问一次"想法够不够写下一段"（论文 T=20）
            "probe_every_tokens": 20,
            #: writer 走到段落边界（空行）时先停，等新的想法
            "pause_on_paragraph": True,
            #: 论文 Figure 4 的 +Δ：给 yes 的对数概率加固定偏置
            "yes_bias": 0.0,
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
    "memory": {
        "delta_mem": {
            "enabled": False,
            "weights": "",
            "rank": 64,
            "n_states": 1,
            "chunk": 16,
            "alpha": 16.0,
            #: 注入强度缩放：乘在**每层学出来的 log_alpha** 上（config.alpha 只是初始化值）
            "alpha_scale": 1.0,
            "layers": "",
            "calibrate_on_load": False,
            #: 写记忆一趟前向的窗口（0 = 跟 context.n_ctx）；应与训练时的值一致
            "window": 0,
            #: 权重文件缺失时是否仍用随机初始化挂载（只用于验管道，效果一定更差）
            "allow_untrained": False,
            # 存储：每用户一个独立目录（character/userinfo/<uid>/mem/）
            "layout": "userinfo",
            "userinfo_dir": "../../character/userinfo",
            "formal_pattern": "^\\d{6}$",
            "strict_formal": True,
            "state_dir": "character/memory/.dmem",   # 仅 layout=flat / 迁移源用
            "max_cached_owners": 8,
            "persist": True,
            "backup_keep": 5,
        },
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
            every = self.get("engine.dualstream.probe_every_tokens", 20)
            if not isinstance(every, int) or not (1 <= every <= 512):
                problems.append(
                    f"engine.dualstream.probe_every_tokens 必须在 [1,512]: {every!r}")
            pause = self.get("engine.dualstream.pause_on_paragraph", True)
            if not isinstance(pause, bool):
                problems.append(
                    f"engine.dualstream.pause_on_paragraph 必须是 bool: {pause!r}")
            bias = self.get("engine.dualstream.yes_bias", 0.0)
            if not isinstance(bias, (int, float)) or not (-5.0 <= float(bias) <= 5.0):
                problems.append(f"engine.dualstream.yes_bias 必须在 [-5,5]: {bias!r}")

        for key in ("temperature", "top_p"):
            value = self.get(f"gen.{key}", 0)
            if not isinstance(value, (int, float)):
                problems.append(f"gen.{key} 必须是数字: {value!r}")

        dmem = self.get("memory.delta_mem", {}) or {}
        if not isinstance(dmem, dict):
            problems.append("memory.delta_mem 必须是映射")
        else:
            rank = dmem.get("rank", 64)
            if not isinstance(rank, int) or not (1 <= rank <= 256):
                problems.append(f"memory.delta_mem.rank 必须在 [1,256]: {rank!r}")
            n_states = dmem.get("n_states", 1)
            if not isinstance(n_states, int) or not (1 <= n_states <= 8):
                problems.append(f"memory.delta_mem.n_states 必须在 [1,8]: {n_states!r}")
            chunk = dmem.get("chunk", 16)
            if not isinstance(chunk, int) or not (1 <= chunk <= 512):
                problems.append(f"memory.delta_mem.chunk 必须在 [1,512]: {chunk!r}")
            if dmem.get("enabled") and not str(dmem.get("weights") or "").strip():
                problems.append("memory.delta_mem.enabled=true 时必须给 weights 路径")
            layout = str(dmem.get("layout") or "userinfo").lower()
            if layout not in ("userinfo", "flat"):
                problems.append(f"memory.delta_mem.layout 只能是 userinfo/flat: {layout!r}")
            if layout == "userinfo" and not str(dmem.get("userinfo_dir") or "").strip():
                problems.append("layout=userinfo 时 memory.delta_mem.userinfo_dir 不能为空")
            pattern = str(dmem.get("formal_pattern") or "")
            if pattern:
                try:
                    import re as _re

                    _re.compile(pattern)
                except Exception:  # noqa: BLE001
                    problems.append(f"memory.delta_mem.formal_pattern 不是合法正则: {pattern!r}")
            window = dmem.get("window", 0)
            if not isinstance(window, int) or window < 0 or window > 131072:
                problems.append(f"memory.delta_mem.window 必须在 [0,131072]（0 = 跟 n_ctx）: {window!r}")
            backup_keep = dmem.get("backup_keep", 5)
            if not isinstance(backup_keep, int) or not (0 <= backup_keep <= 100):
                problems.append(f"memory.delta_mem.backup_keep 必须在 [0,100]: {backup_keep!r}")
            if not isinstance(dmem.get("allow_untrained", False), bool):
                problems.append(
                    f"memory.delta_mem.allow_untrained 必须是布尔: "
                    f"{dmem.get('allow_untrained')!r}")
            alpha_scale = dmem.get("alpha_scale", 1.0)
            if not isinstance(alpha_scale, (int, float)) or not (0.05 <= float(alpha_scale) <= 64):
                problems.append(
                    f"memory.delta_mem.alpha_scale 必须在 [0.05,64]（1.0=不变）: "
                    f"{alpha_scale!r}")

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
