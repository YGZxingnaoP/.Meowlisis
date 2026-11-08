# -*- coding: utf-8 -*-
"""兼容入口：真正的实现放在同目录的 memptips.py（历史拼写）。

新代码统一从 ``records.memptips`` 导入；这里只做转发，避免旧调用方
（早期脚本 / 旧 pyc）因为拼写差异读到过期实现。
"""

from .memptips import *  # noqa: F401,F403
from .memptips import VERSION, SOFT_LEN, HARD_LEN, DIMENSIONS  # noqa: F401
