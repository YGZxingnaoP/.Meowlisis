# -*- coding: utf-8 -*-
# func/llm_active/director/config.py
# 导演模块配置项统一管理（节点 llm_active.director）

from func.pipeline.config_reader import ConfigReader
from func.tools.singleton_mode import singleton


@singleton
class AutoDirectorConfig:
    """集中管理 llm_active.director 节点的全部配置项与默认值"""

    def __init__(self):
        cfg = ConfigReader().get('llm_active', {})
        d = cfg.get('director', {}) if isinstance(cfg, dict) else {}

        # 总开关
        self.enabled = bool(d.get('enabled', True))

        # 每轮主链路回复后的无聊判官
        self.judge_enabled = bool(d.get('judge_enabled', True))
        self.judge_history_rounds = int(d.get('judge_history_rounds', 8) or 8)
        self.judge_max_tokens = int(d.get('judge_max_tokens', 320) or 320)

        # 连续几次「整段 cold_time 内没有用户消息」后重写计划
        self.silent_rounds = int(d.get('silent_rounds', 3) or 3)

        # clear / 启动后的冷却（秒）
        self.cooldown_after_clear = float(d.get('cooldown_after_clear', 600) or 0)

        # 规划器
        self.planner_max_tool_rounds = int(d.get('planner_max_tool_rounds', 12) or 12)
        self.planner_max_tokens = int(d.get('planner_max_tokens', 1600) or 1600)

        # 连续几轮拿不到 director_step 就补一次小监工（0=关闭）
        self.stall_turns = int(d.get('stall_turns', 2) or 0)

        # 重启后是否恢复上次导演（默认不恢复，避免几小时前的旧计划复活）
        self.resume_on_start = bool(d.get('resume_on_start', False))
