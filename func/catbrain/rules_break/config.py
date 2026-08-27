# -*- coding: utf-8 -*-
# func/catbrain/rules_break/config.py
# rules_break 独立配置（config.yml 的 rulebreak 节点）

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBRulesBreakConfig:
    """集中管理 rulebreak 节点配置：主线程/QQ 开关 + 独立 DeepSeek 审查端口"""

    def __init__(self):
        cfg = ConfigReader().get('rulebreak', {})

        # 开关：默认开 QQ、关主线程（均可配置）
        self.enabled_msg = cfg.get('enabled_msg', False)
        self.enabled_qq = cfg.get('enabled_qq', True)
        # 触发好感度下限：仅好感度 > 该值的用户才允许触发原则词注入（默认 3）
        self.affinity_min = cfg.get('affinity_min', 3)

        # 独立 DeepSeek 审查配置（不复用 toolbox / catbrain 的 key）
        ds = cfg.get('deepseek', {})
        self.deepseek_api_key = ds.get('api_key', '')
        self.deepseek_base_url = ds.get('base_url', 'https://api.deepseek.com/v1')
        self.deepseek_model = ds.get('model', 'deepseek-chat')
        self.deepseek_temperature = ds.get('temperature', 0.3)
        self.deepseek_max_tokens = ds.get('max_tokens', 512)
