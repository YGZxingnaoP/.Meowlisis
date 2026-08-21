# -*- coding: utf-8 -*-
# func/toolbox/weather/config.py
# Weather（天气查询）模块配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBWeatherConfig:
    """集中管理 weather 节点的全部配置项与默认值"""

    def __init__(self):
        cfg = ConfigReader().get('weather', {})

        # 是否启用天气查询（触发型工具，受 toolcalls 控制）
        self.enabled = cfg.get('enabled', True)
