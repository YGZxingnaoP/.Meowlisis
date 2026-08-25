# -*- coding: utf-8 -*-
# func/toolbox/meowsongs/config.py
# meowsongs 配置汇总：功能开关、播放长度上限、听歌识曲接龙参数
from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class TBMeowSongsConfig:
    """meowsongs 配置管理：读取 config.yml 的 meowsongs 节点"""

    def __init__(self):
        cfg = ConfigReader().get('meowsongs', {})
        self.enabled = bool(cfg.get('enabled', True))
        self.max_duration = int(cfg.get('max_duration', 180) or 180)

        pbt = cfg.get('pass_the_baton', {}) or {}
        self.pbt_enabled = bool(pbt.get('enabled', False))
        self.hum_lines = int(pbt.get('hum_lines', 2) or 2)
        self.hum_energy_threshold = float(pbt.get('energy_threshold', 300) or 300)
        self.f0_voiced_ratio = float(pbt.get('f0_voiced_ratio', 0.6) or 0.6)
        # 稳定帧占比阈值：相邻帧音高差 < f0_stable_half_step 的帧占比 >= 此值才判哼唱
        self.f0_stable_ratio = float(pbt.get('f0_stable_ratio', 0.6) or 0.6)
        # 稳定帧判定：相邻帧音高差 < 此半音数视为稳定帧
        self.f0_stable_half_step = float(pbt.get('f0_stable_half_step', 0.5) or 0.5)
        self.match_threshold = float(pbt.get('match_threshold', 0.55) or 0.55)
        self.cache_seconds = int(pbt.get('cache_seconds', 30) or 30)
        self.hum_collect_sec = float(pbt.get('hum_collect_sec', 7.0) or 7.0)
        self.f0_unique_notes = int(pbt.get('f0_unique_notes', 3) or 3)
        self.ask_prompt = pbt.get('ask_prompt', '') or ''
        self.feeling_prompt = pbt.get('feeling_prompt', '') or ''
