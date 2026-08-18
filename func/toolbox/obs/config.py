# -*- coding: utf-8 -*-
# func/toolbox/obs/config.py
# OBS 配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class ObsConfig:
    """集中管理 obs 节点的连接参数与场景背景音乐配置"""

    def __init__(self):
        cfg = ConfigReader().get('obs', {})

        # 是否启用 OBS 控制
        self.switch = cfg.get('switch', False)

        # OBS WebSocket 地址
        self.url = cfg.get('url', '127.0.0.1')

        # OBS WebSocket 端口
        self.port = cfg.get('port', 4455)

        # OBS WebSocket 密码
        self.password = cfg.get('password', '')

        # 场景名 → 背景音乐路径映射（dict）
        self.song_background = cfg.get('song_background', {})
