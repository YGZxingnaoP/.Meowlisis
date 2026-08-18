# -*- coding: utf-8 -*-
# func/toolbox/vtuber/state.py
# Vtuber 运行时状态单例：当前服装与感情值

from func.tools.singleton_mode import singleton


@singleton
class VtuberState:
    """Vtuber 运行态数据：换装与心情等运行中可变状态"""

    # 当前穿着的服装名
    now_clothes = "便衣"

    # 感情值（累计）
    mood_num = 0
