import os
import json

from func.log.default_log import DefaultLog
from func.tools.singleton_mode import singleton


@singleton
class LLMPsycheBridge:
    def __init__(self):
        """心理状态桥接：仅负责读写与传输当前心理，不含生成逻辑"""
        self.log = DefaultLog().getLogger()
        self._cache = {}
        self._paths = {"main": ".temp/latest_psyche.json", "qq": ".temp/latest_psyche_qq.json"}

    def _path(self, scope):
        """返回指定场景的心理状态文件路径"""
        return self._paths.get(scope, self._paths["main"])

    def get_psyche(self, scope="main"):
        """读取指定场景的当前心理，内存优先，缺失时读文件"""
        if scope in self._cache:
            return self._cache[scope]
        path = self._path(scope)
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._cache[scope] = data
                    return data
        except Exception:
            self.log.exception("读取心理状态失败")
        return {}

    def set_psyche(self, scope, data):
        """写入指定场景的当前心理并落盘"""
        if not isinstance(data, dict):
            return
        self._cache[scope] = data
        path = self._path(scope)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            self.log.exception("写入心理状态失败")
