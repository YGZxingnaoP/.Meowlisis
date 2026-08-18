# -*- coding: utf-8 -*-
# func/toolbox/vtuber/config.py
# Vtuber（VTube Studio）配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class VtuberConfig:
    """集中管理 emote 节点下 VTube Studio 连接参数与默认值"""

    def __init__(self):
        cfg = ConfigReader().get('emote', {})

        # 是否启用 VTube Studio 控制
        self.switch = cfg.get('switch', False)

        # VTube Studio WebSocket 地址
        self.vtuber_websocket = cfg.get('vtuber_websocket', '127.0.0.1:8001')

        # 插件名（与 VTS 授权信息保持一致）
        self.vtuber_pluginName = cfg.get('vtuber_pluginName', '')

        # 插件开发者
        self.vtuber_pluginDeveloper = cfg.get('vtuber_pluginDeveloper', '')

        # VTS 认证 token
        self.vtuber_authenticationToken = cfg.get('vtuber_authenticationToken', '')
