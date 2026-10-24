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

        pbt = cfg.get('pass_the_baton', {}) or {}
        self.pbt_enabled = bool(pbt.get('enabled', False))
        self.hum_lines = int(pbt.get('hum_lines', 2) or 2)
        # 有声帧占比阈值：pyin 判定有声且置信度足够的帧占比 >= 此值才判哼唱
        self.f0_voiced_ratio = float(pbt.get('f0_voiced_ratio', 0.55) or 0.55)
        # 稳定帧占比阈值：相邻帧音高差 < f0_stable_half_step 的帧占比 >= 此值才判哼唱
        self.f0_stable_ratio = float(pbt.get('f0_stable_ratio', 0.6) or 0.6)
        # 稳定帧判定：相邻帧音高差 < 此半音数视为稳定帧
        self.f0_stable_half_step = float(pbt.get('f0_stable_half_step', 0.5) or 0.5)
        self.match_threshold = float(pbt.get('match_threshold', 0.55) or 0.55)
        # 最佳与次优候选的分差下限，低于该值不锁定，交给角色确认
        self.min_margin = float(pbt.get('min_margin', 0.04) or 0.0)
        self.hum_collect_sec = float(pbt.get('hum_collect_sec', 7.0) or 7.0)
        self.f0_unique_notes = int(pbt.get('f0_unique_notes', 3) or 3)
        self.feeling_prompt = pbt.get('feeling_prompt', '') or ''
