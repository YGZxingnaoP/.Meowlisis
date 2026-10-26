import ast

ALLOWED_IMPORT_ROOTS = {"json", "time", "re", "math", "random", "datetime", "typing",
                        "cw_script", "io", "base64", "PIL"}
FORBIDDEN_NAMES = {"eval", "exec", "compile", "__import__", "globals", "locals", "breakpoint",
                   "input", "open"}
FORBIDDEN_MODULE_ROOTS = {"os", "sys", "subprocess", "socket", "shutil", "ctypes", "importlib",
                          "urllib", "http", "requests", "pathlib", "threading", "multiprocessing",
                          "asyncio", "pickle", "marshal", "builtins"}


class CWActionReview:
    def __init__(self, config):
        self.config = config

    def review(self, files):
        errors = []
        if not files:
            errors.append("没有任何文件")
            return errors
        if len(files) > self.config.action_max_files:
            errors.append("文件数超过 %d" % self.config.action_max_files)
        total = 0
        for name, code in files.items():
            if not str(name).endswith(".py"):
                continue
            body = code or ""
            total += len(body.encode("utf-8"))
            errors.extend("%s: %s" % (name, item) for item in self.review_code(body))
        if total > self.config.action_max_bytes:
            errors.append("脚本总大小超过 %d 字节" % self.config.action_max_bytes)
        return errors

    def review_code(self, code):
        errors = []
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
                    if root not in ALLOWED_IMPORT_ROOTS:
                        errors.append("禁止 import %s" % alias.name)
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root and root not in ALLOWED_IMPORT_ROOTS:
                    errors.append("禁止 from %s import" % node.module)
                if root in FORBIDDEN_MODULE_ROOTS:
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
        try:
            compile(str(code or ""), "<action>", "main")
        except SyntaxError as exc:
            return ["compile 失败：%s" % exc]
        return []
