# -*- coding: utf-8 -*-
# func/toolbox/turtle_soup/config.py
# 海龟汤配置：只读 config.yml 的 turtle_soup 节点（无超时/难度/回合，均由触发者控制）

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBTurtleSoupConfig:
    """海龟汤配置管理"""

    def __init__(self):
        cfg = ConfigReader().get('turtle_soup', {})

        self.enabled = bool(cfg.get('enabled', True))
        self.qq_enabled = bool(cfg.get('qq_enabled', True))

        self.bank_dir = cfg.get('bank_dir', './character/turtle_soup')
        self.cache_dir = cfg.get('cache_dir', './.temp/turtle_soup')

        surface_len = cfg.get('surface_len', {}) or {}
        self.surface_easy_len = int(surface_len.get('easy', 20) or 20)
        self.surface_hard_len = int(surface_len.get('hard', 40) or 40)
