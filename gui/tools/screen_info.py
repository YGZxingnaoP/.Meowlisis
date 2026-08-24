# -*- coding: utf-8 -*-
# gui/tools/screen_info.py
# 屏幕信息获取工具：返回主显示器真实分辨率，供 VTS 窗口预览按屏幕比例等比缩放

import sys


def get_screen_info():
    """获取当前屏幕（主显示器）真实分辨率。

    - Windows 下使用 user32.GetSystemMetrics，坐标系统与 tkinter 创建置顶窗口
      （root.geometry）完全一致，比浏览器 window.screen 更准确（多显示器 / DPI
      缩放下两者可能不同）；
    - 非 Windows 平台返回兜底值 1920x1080。

    :return: dict {
        "width": 主显示器宽,
        "height": 主显示器高,
        "ratio": 宽高比,
        "virtual_width": 多显示器合并虚拟屏宽,
        "virtual_height": 多显示器合并虚拟屏高,
        "source": 数据来源标记,
    }
    """
    if sys.platform != 'win32':
        return {
            'width': 1920,
            'height': 1080,
            'ratio': round(1920 / 1080, 6),
            'virtual_width': 1920,
            'virtual_height': 1080,
            'source': 'fallback',
        }

    import ctypes
    user32 = ctypes.windll.user32
    # SM_CXSCREEN=0 / SM_CYSCREEN=1：主显示器尺寸
    w = int(user32.GetSystemMetrics(0))
    h = int(user32.GetSystemMetrics(1))
    if w <= 0 or h <= 0:
        raise RuntimeError('GetSystemMetrics returned zero')
    # SM_CXVIRTUALSCREEN=78 / SM_CYVIRTUALSCREEN=79：多显示器合并后的虚拟屏
    vw = int(user32.GetSystemMetrics(78)) or w
    vh = int(user32.GetSystemMetrics(79)) or h
    return {
        'width': w,
        'height': h,
        'ratio': round(w / h, 6) if h else 0,
        'virtual_width': vw,
        'virtual_height': vh,
        'source': 'ctypes.GetSystemMetrics',
    }
