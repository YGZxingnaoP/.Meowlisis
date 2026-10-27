import ast
import os

ALLOWED_IMPORT_ROOTS = {"json", "time", "re", "math", "random", "datetime", "typing",
                        "cw_script", "io", "base64", "PIL"}
FORBIDDEN_NAMES = {"eval", "exec", "compile", "__import__", "globals", "locals", "breakpoint",
                   "input", "open"}
FORBIDDEN_MODULE_ROOTS = {"os", "sys", "subprocess", "socket", "shutil", "ctypes", "importlib",
                          "urllib", "http", "requests", "pathlib", "threading", "multiprocessing",
                          "asyncio", "pickle", "marshal", "builtins"}


class CWActionReview:
    """action 脚本审查：import 白名单、行数/体积上限、禁止危险调用"""

    def __init__(self, config):
        self.config = config

    def review(self, files, local_modules=None):
        """整批审查：同一 action 目录里的 .py 互为本地模块，可以互相 import"""
        errors = []
        if not files:
            errors.append("没有任何文件")
            return errors
        if len(files) > self.config.action_max_files:
            errors.append("文件数超过 %d" % self.config.action_max_files)
        modules = set(local_modules or [])
        for name in files:
            if str(name).endswith(".py"):
                modules.add(os.path.splitext(str(name))[0])
        total = 0
        for name, code in files.items():
            if not str(name).endswith(".py"):
                continue
            body = code or ""
            total += len(body.encode("utf-8"))
            errors.extend("%s: %s" % (name, item)
                          for item in self.review_code(body, modules))
        if total > self.config.action_max_bytes:
            errors.append("脚本总大小超过 %d 字节" % self.config.action_max_bytes)
        return errors

    def review_code(self, code, local_modules=None):
        """单文件审查（local_modules = 同目录可 import 的模块名）"""
        errors = []
        modules = set(local_modules or [])
        lines = str(code or "").splitlines()
        if len(lines) > 800:
            errors.append("超过 800 行")
        try:
            tree = ast.parse(str(code or ""))
        except SyntaxError as exc:
            errors.append("语法错误：%s" % exc)
            return errors
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in ALLOWED_IMPORT_ROOTS or root in modules:
                        continue
                    errors.append("禁止 import %s" % alias.name)
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in FORBIDDEN_MODULE_ROOTS:
                    errors.append("禁止 from %s import" % node.module)
                elif root and root not in ALLOWED_IMPORT_ROOTS and root not in modules:
                    errors.append("禁止 from %s import" % node.module)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in FORBIDDEN_NAMES:
                    errors.append("禁止调用 %s" % func.id)
                if isinstance(func, ast.Attribute):
                    base = func.value
                    if isinstance(base, ast.Name) and base.id in FORBIDDEN_MODULE_ROOTS:
                        errors.append("禁止调用 %s.%s" % (base.id, func.attr))
        return errors

    def compile_only(self, code):
        """只做语法编译检查"""
        try:
            compile(str(code or ""), "<action>", "main")
        except SyntaxError as exc:
            return ["compile 失败：%s" % exc]
        return []
