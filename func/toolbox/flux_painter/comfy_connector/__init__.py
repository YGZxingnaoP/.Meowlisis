# -*- coding: utf-8 -*-
# func/toolbox/flux_painter/comfy_connector/__init__.py
from .comfy_painter import TBComfyPainter
from .comfy_port import TBComfyPort
from .artist import TBArtistPicker


def create_connector(config):
    """按 config.comfy_mode 返回内置/外部连接器"""
    if config.comfy_mode == "external":
        return TBComfyPort(config)
    return TBComfyPainter(config)
