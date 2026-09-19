import importlib.util
import os

import yaml


def plugin_dir(root, plugin_id):
    """插件目录绝对路径"""
    return os.path.join(root, str(plugin_id))


def config_path(plugin_dir_path):
    """插件独立配置文件路径"""
    return os.path.join(plugin_dir_path, "config.yml")


def load_schema(plugin_dir_path):
    """读取插件 schema.py（纯数据），返回 (meta, cards, fields)"""
    path = os.path.join(plugin_dir_path, "schema.py")
    if not os.path.isfile(path):
        return {}, [], []
    name = "meowschema_" + os.path.basename(plugin_dir_path)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return {}, [], []
    meta = dict(getattr(module, "PLUGIN", {}) or {})
    cards = list(getattr(module, "CARDS", []) or [])
    fields = list(getattr(module, "FIELDS", []) or [])
    return meta, cards, fields


def list_plugins(root):
    """扫描插件目录，返回 [(id, 目录, meta, cards, fields)]"""
    result = []
    if not root or not os.path.isdir(root):
        return result
    for name in sorted(os.listdir(root)):
        if name.startswith("_") or name.startswith("."):
            continue
        path = os.path.join(root, name)
        if not os.path.isdir(path) or not os.path.isfile(os.path.join(path, "plugin.py")):
            continue
        meta, cards, fields = load_schema(path)
        meta.setdefault("id", name)
        result.append((name, path, meta, cards, fields))
    return result


def default_config(fields):
    """按字段默认值生成配置（支持点号路径）"""
    data = {}
    for field in fields or []:
        key = str(field.get("key") or "").strip()
        if not key:
            continue
        _set(data, key.split("."), field.get("default"))
    return data


def merge_defaults(data, fields):
    """用默认值补齐缺失字段"""
    return _deep_merge(default_config(fields), data or {})


def read_config(plugin_dir_path):
    """读取插件独立配置（缺失返回空 dict）"""
    path = config_path(plugin_dir_path)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_config(plugin_dir_path, data):
    """写入插件独立配置"""
    os.makedirs(plugin_dir_path, exist_ok=True)
    with open(config_path(plugin_dir_path), "w", encoding="utf-8") as f:
        yaml.dump(data or {}, f, allow_unicode=True, sort_keys=False)


def ensure_config(plugin_dir_path, meta=None, fields=None):
    """确保插件配置文件存在并返回补全后的配置"""
    if meta is None and fields is None:
        meta, _cards, fields = load_schema(plugin_dir_path)
    data = merge_defaults(read_config(plugin_dir_path), fields)
    if not os.path.isfile(config_path(plugin_dir_path)):
        write_config(plugin_dir_path, data)
    return data


def _set(obj, parts, value):
    """按路径写入嵌套 dict"""
    cur = obj
    for key in parts[:-1]:
        if not isinstance(cur.get(key), dict):
            cur[key] = {}
        cur = cur[key]
    cur[parts[-1]] = value


def _deep_merge(base, override):
    """深度合并（override 覆盖 base）"""
    out = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
