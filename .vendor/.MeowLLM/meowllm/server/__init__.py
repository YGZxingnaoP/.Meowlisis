# -*- coding: utf-8 -*-
"""HTTP 服务层。

刻意不在这里 import app：否则 `python -m meowllm.server.app` 会先因包导入
把 app 模块加载进 sys.modules，触发 runpy 的 RuntimeWarning。
需要时请显式 `from meowllm.server.app import create_app, main`。
"""

__all__: list[str] = []
