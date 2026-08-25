# -*- coding: utf-8 -*-
# func/vts/desktopet/state.py
# 桌宠运行时状态单例

from func.tools.singleton_mode import singleton


@singleton
class DesktopetState:
    """桌宠运行态数据（预留换装等运行中可变状态）"""

    now_clothes = "便衣"
