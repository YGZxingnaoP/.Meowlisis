# -*- coding: utf-8 -*-
# func/toolbox/add_backlog/config.py
# Add Backlog（新建待办）模块配置项统一管理

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBAddBacklogConfig:
    """集中管理 add_backlog 节点的全部配置项与默认值"""

    def __init__(self):
        cfg = ConfigReader().get('add_backlog', {})

        # 是否启用新建待办（触发型工具，受 toolcalls 控制）
        self.enabled = cfg.get('enabled', True)
        # 是否启用 QQ 对接（QQ 私聊 + 群聊@ 触发）
        self.qq_enabled = cfg.get('qq_enabled', True)
