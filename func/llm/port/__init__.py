# -*- coding: utf-8 -*-
# func/llm/port/__init__.py
# LLM 端口公共工具

import threading
import time


def close_port_later(port, delay: float = 60.0):
    """延迟关闭端口持有的 HTTP 客户端（热重载重建客户端时用）。

    为什么要延迟：重建只做"换引用"，正在跑的流式回复还握着旧 client；
    立即 close 会把那条回复掐断。等一会儿再关，既不打断在途请求，也不泄漏连接池。
    """
    if port is None:
        return

    def _run():
        time.sleep(max(0.0, float(delay)))
        try:
            client = getattr(port, "client", None)
            if client is not None and hasattr(client, "close"):
                client.close()
        except Exception:
            pass

    try:
        threading.Thread(target=_run, daemon=True, name="llm-port-close").start()
    except Exception:
        pass
