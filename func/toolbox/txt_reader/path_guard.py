# -*- coding: utf-8 -*-
# func/tools/analysis/path_guard.py
# 企业级文件分析工具的路径安全守卫

import os

from func.log.default_log import DefaultLog


class MeowPathGuard:
    """路径守卫：将相对路径解析为绝对路径并限制在允许的根目录内"""

    # 允许访问的根目录（相对项目根）
    ALLOWED_ROOTS = ["character", ".temp", "func", "logs"]

    def __init__(self):
        self.log = DefaultLog().getLogger()
        self.project_root = os.getcwd()

    def resolve(self, path: str) -> str:
        """解析路径为绝对路径，越界或非法时返回空字符串"""
        if not path:
            return ""
        try:
            abs_path = os.path.abspath(os.path.join(self.project_root, path))
        except Exception:
            return ""
        # 防止路径穿越：必须位于项目根目录内
        if not abs_path.startswith(self.project_root):
            self.log.warning(f"路径越界被拦截: {path}")
            return ""
        # 必须位于允许的根目录内
        rel = os.path.relpath(abs_path, self.project_root)
        top = rel.split(os.sep)[0]
        if top not in self.ALLOWED_ROOTS:
            self.log.warning(f"路径不在允许目录内被拦截: {path}")
            return ""
        return abs_path

    def is_safe(self, path: str) -> bool:
        """判断路径是否安全可用"""
        return bool(self.resolve(path))
