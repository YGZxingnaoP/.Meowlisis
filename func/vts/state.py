# -*- coding: utf-8 -*-
# func/vts/state.py
# VTS 运行时状态单例：当前服装

from func.tools.singleton_mode import singleton


@singleton
class VtsState:
    """VTS 运行态数据：换装等运行中可变状态"""

    # 当前穿着的服装名
    now_clothes = "便衣"
