# -*- coding: utf-8 -*-
# func/config/app_config.py
# 全局应用配置：AI 名称、运行模式、API 端口

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class AppConfig:
    """集中管理根级 AiName 与 app 节点的配置项与默认值"""

    def __init__(self):
        root = ConfigReader().get()
        app = root.get('app', {})

        # AI 名称（根级）
        self.ai_name = root.get('AiName', '喵呜')

        # API Web 端口
        self.port = app.get('port', 1800)
