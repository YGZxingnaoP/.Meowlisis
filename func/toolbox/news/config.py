# -*- coding: utf-8 -*-
# func/toolbox/news/config.py
# News（新闻查询）模块配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBNewsConfig:
    """集中管理 news 节点的全部配置项与默认值"""

    def __init__(self):
        cfg = ConfigReader().get('news', {})

        # 是否启用新闻查询（触发型工具，受 toolcalls 控制）
        self.enabled = cfg.get('enabled', True)
        # 每次爬取并概括的新闻条数
        self.top_n = cfg.get('top_n', 3)
