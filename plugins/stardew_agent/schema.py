# -*- coding: utf-8 -*-
"""星露谷 AI 玩家：GUI 配置面板 schema。

GUI 用 importlib 直接 exec 这个文件，不会把它当成包成员；
所以这里不能用 `from .core.schema import FIELDS`，否则相对导入失败，
前端就会把插件当成“没有配置项”。
"""

import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_CORE_SCHEMA = os.path.join(_HERE, "core", "schema.py")

FIELDS = []
try:
    _spec = importlib.util.spec_from_file_location("stardew_core_schema", _CORE_SCHEMA)
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    FIELDS = list(getattr(_module, "FIELDS", []) or [])
except Exception:
    FIELDS = []

PLUGIN = {
    "id": "stardew_agent",
    "title": "星露谷 AI 玩家",
    "version": "0.8.1",
    "group": "game",
    "emoji": "\U0001F33E",          # 🌾
    "default_enabled": False,
}
