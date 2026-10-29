# -*- coding: utf-8 -*-
# func/toolbox/napcat/director/config.py
# QQ 导演配置（节点 napcat.director_qq）

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class QQDirectorConfig:
    """QQ 导演（简化版）配置项与默认值"""

    def __init__(self):
        root = ConfigReader().get()
        cfg = root.get('napcat', {}) or {}
        d = cfg.get('director_qq', {}) or {}
        # 总开关：关掉后判官/块/推进全部跳过
        self.enabled = bool(d.get('enabled', True))
        # 判官输出上限（只调一个工具，输出很短）
        self.judge_max_tokens = int(d.get('judge_max_tokens', 200) or 200)
        # 每次起戏最多给几步
        self.max_steps = int(d.get('max_steps', 3) or 3)
